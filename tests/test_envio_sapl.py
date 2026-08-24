"""Regressao do envio automatico ao SAPL.

Aqui nao se testa "a funcao devolve o valor certo". Testa-se o que acontece
quando ela erra, porque cada erro destes vira registro publico da Camara:

  - dizer que salvou sem ter salvado -> a indicacao some do acervo e ninguem
    procura por ela de novo, porque o programa a marcou como enviada;
  - deixar passar uma indicacao ja cadastrada -> duas materias para o mesmo
    documento;
  - enviar com a correcao antiga -> a ementa que a pessoa transcreveu do papel
    fica no arquivo e a que o OCR errou vira o registro oficial.

    .venv\\Scripts\\python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import enviados as mod_enviados
from src import sapl
from src.revisao import divergencias_da_correcao, identificador_lido

FORM = {
    "campos": {
        "ementa": ["#id_ementa", "textarea[name='ementa']"],
    },
    "botao_salvar": ["#submit-id-salvar", "input[type='submit'][name='salvar']"],
    "erros": ["ul.errorlist li", ".alert-danger"],
    "url_sucesso": r"/materia/(\d+)",
}

FORMULARIO = "https://sapl.parnamirim.rn.leg.br/materia/create"


def indicacao(**kwargs) -> dict:
    """Uma indicacao como ela sai em output/indicacoes.json - pronta e limpa."""
    base = dict(
        numero=1405, numero_lido=1405, ano=2022, status="pronto",
        ementa="INDICA A PODA DAS ÁRVORES DA RUA TAL, NO BAIRRO TAL.",
        data_apresentacao="16/12/2022", autor_id=11,
        autor_nome_sapl="Binho de Ambrósio",
    )
    base.update(kwargs)
    return base


# --------------------------------------------------------------------- fakes


class Elemento:
    """O que o Playwright devolve em locator(...): conta, first, textos."""

    def __init__(self, quantos: int = 1, textos: list[str] | None = None):
        self.quantos = quantos
        self.textos = textos or []
        self.cliques = 0

    def count(self) -> int:
        return self.quantos

    @property
    def first(self) -> "Elemento":
        return self

    def all_inner_texts(self) -> list[str]:
        return self.textos

    def evaluate(self, js: str):
        return "select"

    def input_value(self) -> str:
        return self.valor

    valor = ""

    def scroll_into_view_if_needed(self, timeout: int = 0) -> None:
        pass

    def click(self, timeout: int = 0) -> None:
        self.cliques += 1
        if self.ao_clicar is not None:
            self.ao_clicar()

    ao_clicar = None


class RespostaFalsa:
    """A resposta de rede, na fatia que sapl._vigiar_navegacao le.

    No Playwright o status esta na Response e o "isto e navegacao?" esta na
    Request pendurada nela - por isso as duas.
    """

    class _Pedido:
        def __init__(self, frame):
            self.frame = frame

        def is_navigation_request(self) -> bool:
            return True

    def __init__(self, status: int, url: str, frame):
        self.status = status
        self.url = url
        self.request = self._Pedido(frame)


class PaginaFalsa:
    """Uma pagina do SAPL sem SAPL nenhum.

    Guarda um mapa seletor -> Elemento e troca esse mapa quando o botao de
    salvar e clicado, que e exatamente o que o navegador faz de verdade:
    responde outra pagina.
    """

    def __init__(self, url: str, elementos: dict[str, Elemento],
                 depois_do_clique=None):
        self.url = url
        self.elementos = elementos
        self.depois_do_clique = depois_do_clique
        self.fechada = False
        self.esperas = 0
        self.marcado = False
        # So precisa ser comparavel por identidade: e assim que src/sapl.py
        # separa a navegacao do documento principal da de um iframe.
        self.main_frame = object()
        self.ouvintes: list = []

        botao = elementos.get("#submit-id-salvar")
        if botao is not None:
            botao.ao_clicar = self._clicou

    def _clicou(self) -> None:
        if self.depois_do_clique:
            self.depois_do_clique(self)

    def trocar_documento(self, status: int = 200) -> None:
        """O navegador carregou outra pagina: o window de antes morreu, e com
        ele o carimbo que src/sapl.py deixou la.

        Toda navegacao de verdade traz um status HTTP junto, entao ele sai
        daqui tambem - inclusive quando a pagina nova e de erro.
        """
        self.marcado = False
        self.responder_http(status)

    def responder_http(self, status: int) -> None:
        for ouvinte in list(self.ouvintes):
            ouvinte(RespostaFalsa(status, self.url, self.main_frame))

    def on(self, evento: str, funcao) -> None:
        if evento == "response":
            self.ouvintes.append(funcao)

    def remove_listener(self, evento: str, funcao) -> None:
        if evento == "response" and funcao in self.ouvintes:
            self.ouvintes.remove(funcao)

    # --- a fatia da API do Playwright que src/sapl.py realmente usa ---
    def locator(self, seletor: str) -> Elemento:
        return self.elementos.get(seletor, Elemento(quantos=0))

    def is_closed(self) -> bool:
        return self.fechada

    def wait_for_timeout(self, ms: int) -> None:
        self.esperas += 1

    def wait_for_load_state(self, estado: str, timeout: int = 0) -> None:
        pass

    def evaluate(self, js: str):
        # "!==" so aparece na PERGUNTA ("o carimbo ainda esta aqui?"); a outra
        # chamada e a que poe o carimbo.
        if "!==" in js:
            return not self.marcado
        self.marcado = True
        return None


def pagina_do_formulario(**kwargs) -> PaginaFalsa:
    return PaginaFalsa(
        FORMULARIO,
        {
            "#id_ementa": Elemento(),
            "#submit-id-salvar": Elemento(),
        },
        **kwargs,
    )


# ---------------------------------------------------------------- divergencia


class TestDivergenciaDaCorrecao(unittest.TestCase):
    """A correcao que voce digitou chegou nesta indicacao?"""

    def test_sem_correcao_nao_ha_divergencia(self):
        self.assertEqual(divergencias_da_correcao(indicacao(), {}), [])

    def test_correcao_aplicada_nao_acusa_nada(self):
        correcoes = {"1405/2022": {
            "ementa": "INDICA A PODA DAS ÁRVORES DA RUA TAL, NO BAIRRO TAL.",
            "data": "16/12/2022",
            "autor_id": 11,
        }}
        self.assertEqual(divergencias_da_correcao(indicacao(), correcoes), [])

    def test_ementa_velha_e_acusada(self):
        """O caso que motivou a conferencia: a pessoa transcreveu a ementa na
        aba 2 e mandou para o SAPL antes de processar o lote de novo."""
        correcoes = {"1405/2022": {"ementa": "TEXTO CERTO, TRANSCRITO DO PAPEL"}}
        problemas = divergencias_da_correcao(indicacao(), correcoes)
        self.assertEqual(len(problemas), 1)
        self.assertIn("ementa", problemas[0])

    def test_data_velha_e_acusada(self):
        correcoes = {"1405/2022": {"data": "03/03/2022"}}
        problemas = divergencias_da_correcao(indicacao(), correcoes)
        self.assertEqual(len(problemas), 1)
        self.assertIn("03/03/2022", problemas[0])

    def test_autor_velho_e_acusado(self):
        correcoes = {"1405/2022": {"autor_id": 12}}
        problemas = divergencias_da_correcao(indicacao(), correcoes)
        self.assertEqual(len(problemas), 1)
        self.assertIn("12", problemas[0])

    def test_numero_velho_e_acusado(self):
        """Numero corrigido e o pior dos casos: o cadastro sairia com o numero
        errado E com o PDF de outra indicacao anexado."""
        correcoes = {"9/2022": {"numero": 1629}}
        item = indicacao(numero=9, numero_lido=9)
        problemas = divergencias_da_correcao(item, correcoes)
        self.assertEqual(len(problemas), 1)
        self.assertIn("1629", problemas[0])

    def test_chave_e_o_numero_lido_nao_o_corrigido(self):
        """Depois de aplicada, a indicacao tem numero 1629 mas a correcao
        continua guardada em "9/2022" - se a busca usasse o numero novo, toda
        indicacao corrigida pareceria nao ter correcao nenhuma."""
        item = indicacao(numero=1629, numero_lido=9)
        self.assertEqual(identificador_lido(item), "9/2022")
        correcoes = {"9/2022": {"numero": 1629, "ementa": "OUTRA COISA"}}
        problemas = divergencias_da_correcao(item, correcoes)
        self.assertEqual(len(problemas), 1)   # so a ementa; o numero bate
        self.assertIn("ementa", problemas[0])

    def test_autor_id_invalido_no_glossario(self):
        correcoes = {"1405/2022": {"autor_id_invalido": "Binho"}}
        problemas = divergencias_da_correcao(indicacao(), correcoes)
        self.assertEqual(len(problemas), 1)
        self.assertIn("Binho", problemas[0])


# --------------------------------------------------------------- impedimentos


class TestImpedimentos(unittest.TestCase):
    """O que pode e o que nao pode ir sozinho para o SAPL."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pdfs = self.tmp / "pdfs"
        self.pdfs.mkdir()
        (self.pdfs / "1405-2022.pdf").write_bytes(b"%PDF-1.4\n")
        # caminho_do_pdf importa PDFS_DIR na chamada, entao trocar aqui basta.
        from src import config
        self._pdfs_dir = config.PDFS_DIR
        config.PDFS_DIR = self.pdfs

    def tearDown(self):
        from src import config
        config.PDFS_DIR = self._pdfs_dir

    def test_indicacao_limpa_passa(self):
        self.assertEqual(sapl.impedimentos(indicacao(), {}, {}), [])

    def test_status_revisao_nao_passa(self):
        travas = sapl.impedimentos(indicacao(status="revisao"), {}, {})
        self.assertTrue(any("revisao" in t or "revisão" in t for t in travas))

    def test_ja_enviada_nao_passa(self):
        enviados = {"1405/2022": {"em": "2026-08-14T09:00:00", "url": "x"}}
        travas = sapl.impedimentos(indicacao(), {}, enviados)
        self.assertTrue(any("já foi cadastrada" in t for t in travas))

    def test_sem_data_nao_passa(self):
        travas = sapl.impedimentos(indicacao(data_apresentacao=""), {}, {})
        self.assertIn("sem data de apresentação", travas)

    def test_sem_autor_nao_passa(self):
        """Autor vazio e leitura que falhou: tem de parar."""
        travas = sapl.impedimentos(indicacao(autor_id=0), {}, {})
        self.assertIn("sem autor definido", travas)

    def test_marcada_como_sem_autor_passa(self):
        """A 439/2023 e assinada por todos os vereadores - nao ha autor
        individual, e voce marcou isso na conferencia. Essa passa."""
        travas = sapl.impedimentos(
            indicacao(autor_id=0, sem_autor=True), {}, {})
        self.assertNotIn("sem autor definido", travas)

    def test_sem_ementa_nao_passa(self):
        travas = sapl.impedimentos(indicacao(ementa="   "), {}, {})
        self.assertIn("sem ementa", travas)

    def test_sem_pdf_nao_passa(self):
        """Sem o PDF a materia entraria no SAPL sem o texto original - um
        registro oficial incompleto, que so se descobre abrindo a materia."""
        travas = sapl.impedimentos(indicacao(numero=999), {}, {})
        self.assertTrue(any("999-2022.pdf" in t for t in travas))

    def test_correcao_pendente_nao_passa(self):
        correcoes = {"1405/2022": {"ementa": "TEXTO CERTO, TRANSCRITO DO PAPEL"}}
        travas = sapl.impedimentos(indicacao(), correcoes, {})
        self.assertTrue(any(t.startswith("correção não aplicada") for t in travas))

    def test_varios_problemas_aparecem_juntos(self):
        """A pessoa tem de ver tudo de uma vez, nao um por rodada."""
        travas = sapl.impedimentos(
            indicacao(status="revisao", autor_id=0, data_apresentacao=""), {}, {})
        self.assertGreaterEqual(len(travas), 3)


# ------------------------------------------------------------------- salvar


class TestSalvar(unittest.TestCase):
    """A pergunta mais perigosa do programa: isto entrou mesmo no SAPL?"""

    def test_sucesso_quando_vai_para_a_materia_criada(self):
        def responder(pagina):
            pagina.url = "https://sapl.parnamirim.rn.leg.br/materia/4321"
            pagina.elementos = {}          # a materia criada nao tem formulario
            pagina.trocar_documento()

        salvou, recado, url = sapl.salvar(pagina_do_formulario(
            depois_do_clique=responder), FORM, espera_ms=3000)
        self.assertTrue(salvou)
        self.assertIn("4321", recado)
        self.assertTrue(url.endswith("/materia/4321"))

    def test_recusa_do_sapl_nao_vira_sucesso(self):
        """Erro de validacao redesenha o MESMO formulario, na MESMA URL."""
        def responder(pagina):
            pagina.elementos["ul.errorlist li"] = Elemento(
                textos=["Este campo é obrigatório."])
            pagina.trocar_documento()

        salvou, recado, url = sapl.salvar(pagina_do_formulario(
            depois_do_clique=responder), FORM, espera_ms=30000)
        self.assertFalse(salvou)
        self.assertIn("recusou", recado)
        self.assertIn("obrigat", recado)
        self.assertEqual(url, "")

    def test_recusa_e_percebida_na_hora_nao_no_fim_do_tempo(self):
        """A recusa acontece na mesma URL. Se so a mudanca de endereco contasse
        como resposta, cada indicacao recusada faria a sessao inteira esperar o
        tempo cheio - dois minutos parado por indicacao, sem motivo."""
        import time as _t

        def responder(pagina):
            pagina.elementos["ul.errorlist li"] = Elemento(textos=["Erro."])
            pagina.trocar_documento()

        comeco = _t.monotonic()
        sapl.salvar(pagina_do_formulario(depois_do_clique=responder),
                    FORM, espera_ms=60000)
        self.assertLess(_t.monotonic() - comeco, 5)

    def test_sessao_caida_nao_vira_sucesso(self):
        """O SAPL joga para o login: some o formulario, muda a URL. Sem a
        conferencia de login isto pareceria um cadastro perfeito."""
        def responder(pagina):
            pagina.url = "https://sapl.parnamirim.rn.leg.br/login/?next=/materia/create"
            pagina.elementos = {}
            pagina.trocar_documento()

        salvou, recado, url = sapl.salvar(pagina_do_formulario(
            depois_do_clique=responder), FORM, espera_ms=3000)
        self.assertFalse(salvou)
        self.assertIn("sessão", recado)

    def test_pagina_de_erro_do_servidor_nao_vira_sucesso(self):
        """O caso real: depois do clique a janela do Firefox mostrava o 404 CRU
        DO NGINX - aquela pagina branca com "nginx/1.22.1" embaixo.

        Ela passava nos dois testes que existiam: nao tem campo de ementa
        (logo, "saiu do formulario") e nao tem "login" na URL (logo, "a sessao
        esta viva"). Resultado: o programa dizia "cadastrada", gravava a
        indicacao no registro de enviados e nunca mais a mostrava - enquanto a
        materia nao existia no SAPL. E o unico erro daqui que ninguem descobre,
        porque a indicacao some da fila justamente por ter "dado certo".
        """
        def responder(pagina):
            pagina.url = "https://sapl.parnamirim.rn.leg.br/media/sapl/public/x.pdf"
            pagina.elementos = {}
            pagina.trocar_documento(status=404)

        salvou, recado, url = sapl.salvar(pagina_do_formulario(
            depois_do_clique=responder), FORM, espera_ms=3000)
        self.assertFalse(salvou)
        self.assertIn("404", recado)
        self.assertEqual(url, "")

    def test_erro_de_servidor_tambem_nao_vira_sucesso(self):
        """500 na cara do salvamento e o mesmo estrago que o 404."""
        def responder(pagina):
            pagina.url = "https://sapl.parnamirim.rn.leg.br/materia/create"
            pagina.elementos = {}
            pagina.trocar_documento(status=500)

        salvou, recado, _ = sapl.salvar(pagina_do_formulario(
            depois_do_clique=responder), FORM, espera_ms=3000)
        self.assertFalse(salvou)
        self.assertIn("500", recado)

    def test_status_nao_observado_nao_inventa_recusa(self):
        """Navegacao que nao passou pela rede (cache, aba trocada) deixa o
        status em 0. Ai vale o criterio antigo - o conserto so pode acrescentar
        motivo para RECUSAR, nunca fazer o envio parar de funcionar."""
        def responder(pagina):
            pagina.url = "https://sapl.parnamirim.rn.leg.br/materia/4321"
            pagina.elementos = {}
            pagina.marcado = False        # troca o documento SEM status nenhum

        salvou, recado, _ = sapl.salvar(pagina_do_formulario(
            depois_do_clique=responder), FORM, espera_ms=3000)
        self.assertTrue(salvou)
        self.assertIn("4321", recado)

    def test_o_vigia_nao_fica_pendurado_na_pagina(self):
        """A pagina e a MESMA durante o lote inteiro (o worker so faz goto).
        Um ouvinte por indicacao ficaria acumulando, e todos anotando no estado
        de chamadas que ja terminaram."""
        def responder(pagina):
            pagina.url = "https://sapl.parnamirim.rn.leg.br/materia/4321"
            pagina.elementos = {}
            pagina.trocar_documento()

        pagina = pagina_do_formulario(depois_do_clique=responder)
        for _ in range(3):
            pagina.url = FORMULARIO
            pagina.elementos = {"#id_ementa": Elemento(),
                                "#submit-id-salvar": Elemento()}
            pagina.elementos["#submit-id-salvar"].ao_clicar = pagina._clicou
            sapl.salvar(pagina, FORM, espera_ms=3000)
        self.assertEqual(pagina.ouvintes, [])

    def test_pagina_que_nao_responde_nao_vira_sucesso(self):
        salvou, recado, url = sapl.salvar(
            pagina_do_formulario(), FORM, espera_ms=600)
        self.assertFalse(salvou)
        self.assertIn("não respondeu", recado)

    def test_formulario_de_volta_em_outra_url_nao_vira_sucesso(self):
        """Mudou de endereco mas continua sendo formulario de cadastro: nao da
        para afirmar que salvou, entao nao se afirma."""
        def responder(pagina):
            pagina.url = "https://sapl.parnamirim.rn.leg.br/materia/create?erro=1"
            pagina.trocar_documento()

        salvou, recado, _ = sapl.salvar(pagina_do_formulario(
            depois_do_clique=responder), FORM, espera_ms=3000)
        self.assertFalse(salvou)
        self.assertIn("recusou", recado)

    def test_sem_botao_nao_clica_em_nada(self):
        pagina = PaginaFalsa(FORMULARIO, {"#id_ementa": Elemento()})
        salvou, recado, _ = sapl.salvar(pagina, FORM, espera_ms=600)
        self.assertFalse(salvou)
        self.assertIn("botão de salvar", recado)

    def test_clica_uma_unica_vez(self):
        """O botao do SAPL se desabilita sozinho depois do clique justamente
        para nao gerar materia em dobro. Um segundo clique daqui seria pior
        ainda, porque viria depois de a pagina ja ter respondido."""
        def responder(pagina):
            pagina.url = "https://sapl.parnamirim.rn.leg.br/materia/4321"
            pagina.elementos = {"#submit-id-salvar": botao}
            pagina.trocar_documento()

        pagina = pagina_do_formulario(depois_do_clique=responder)
        botao = pagina.elementos["#submit-id-salvar"]
        sapl.salvar(pagina, FORM, espera_ms=3000)
        self.assertEqual(botao.cliques, 1)

    def test_janela_fechada_no_meio_avisa_para_conferir(self):
        def responder(pagina):
            pagina.fechada = True

        salvou, recado, _ = sapl.salvar(pagina_do_formulario(
            depois_do_clique=responder), FORM, espera_ms=3000)
        self.assertFalse(salvou)
        self.assertIn("confira no SAPL", recado)


# ------------------------------------------------------------ registro de envio


class TestRegistroDeEnviados(unittest.TestCase):
    """A memoria de quem ja virou registro publico."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.arquivo = self.tmp / "enviados.json"

    def test_arquivo_inexistente_e_vazio(self):
        self.assertEqual(mod_enviados.ler_enviados(self.arquivo), {})

    def test_registra_e_le_de_volta(self):
        mod_enviados.registrar_envio("1405/2022", url="http://x/materia/4321",
                                     caminho=self.arquivo)
        lido = mod_enviados.ler_enviados(self.arquivo)
        self.assertIn("1405/2022", lido)
        self.assertEqual(lido["1405/2022"]["url"], "http://x/materia/4321")
        self.assertTrue(lido["1405/2022"]["em"])

    def test_registrar_de_novo_preserva_o_primeiro(self):
        """O primeiro carimbo e o do cadastro real. Sobrescrever apagaria a
        unica pista de quando a materia entrou."""
        mod_enviados.registrar_envio("1405/2022", url="primeira",
                                     caminho=self.arquivo)
        primeiro = mod_enviados.ler_enviados(self.arquivo)["1405/2022"]
        mod_enviados.registrar_envio("1405/2022", url="segunda",
                                     caminho=self.arquivo)
        self.assertEqual(mod_enviados.ler_enviados(self.arquivo)["1405/2022"],
                         primeiro)

    def test_acumula_sem_apagar_o_que_ja_havia(self):
        mod_enviados.registrar_envio("1/2022", caminho=self.arquivo)
        mod_enviados.registrar_envio("2/2022", caminho=self.arquivo)
        self.assertEqual(set(mod_enviados.ler_enviados(self.arquivo)),
                         {"1/2022", "2/2022"})

    def test_arquivo_corrompido_levanta_erro_em_vez_de_vazio(self):
        """Devolver {} aqui significaria "nada foi enviado" e liberaria o
        reenvio do lote inteiro."""
        self.arquivo.write_text("{ isto nao e json", encoding="utf-8")
        with self.assertRaises(ValueError):
            mod_enviados.ler_enviados(self.arquivo)

    def test_formato_inesperado_levanta_erro(self):
        self.arquivo.write_text(json.dumps({"enviados": []}), encoding="utf-8")
        with self.assertRaises(ValueError):
            mod_enviados.ler_enviados(self.arquivo)


class TestPreencherSemAutor(unittest.TestCase):
    """O preenchimento nao pode reclamar de um autor que voce disse nao existir.

    Se reclamasse, o recado ("autor não identificado") pararia o envio
    automatico em TODA indicacao assinada por todos os vereadores - o oposto
    exato do que marcar "não tem autor individual" quer dizer.
    """

    CAMPOS = ("tipo_materia", "ano", "regime_tramitacao", "tipo_apresentacao",
              "data_apresentacao", "ementa", "tipo_autor", "autor", "numero")

    def setUp(self):
        self.form = {"campos": {c: [f"#id_{c}"] for c in self.CAMPOS}}
        self.pagina = PaginaFalsa(
            FORMULARIO, {f"#id_{c}": Elemento() for c in self.CAMPOS})
        # Escrever de fato nos campos e assunto do Playwright; aqui interessa
        # o que preencher() DECIDE, nao como ele digita. Os dublês guardam o
        # valor no elemento porque preencher() RELE o campo numero no fim - o
        # SAPL sugere um numero sozinho e pode sobrescrever o nosso.
        self._originais = (sapl.definir_select, sapl.garantir_select,
                           sapl.definir_texto)

        def escrever(alvo, valor) -> bool:
            alvo.valor = str(valor)
            return True

        sapl.definir_select = lambda p, a, v: escrever(a, v)
        sapl.garantir_select = lambda p, a, v: escrever(a, v)
        sapl.definir_texto = escrever

    def tearDown(self):
        (sapl.definir_select, sapl.garantir_select,
         sapl.definir_texto) = self._originais

    def _item(self, **extra) -> dict:
        base = dict(numero=439, ano=2023, tipo_materia_id=6, tipo_autor_id=2,
                    regime_id=1, tipo_apresentacao="E", autor_id=0,
                    ementa="APOIO DAS FORÇAS ARMADAS.",
                    data_apresentacao="22/03/2023")
        base.update(extra)
        return base

    def test_marcada_como_sem_autor_nao_gera_recado(self):
        falhas, notas = sapl.preencher(self.pagina, self.form,
                                       self._item(sem_autor=True))
        # A afirmacao e sobre o AUTOR. O recado do anexo aparece porque este
        # formulario de teste nao tem o campo de arquivo - e isso e verdade
        # sobre o formulario, nao sobre a indicacao.
        sobre_autor = [m for m in falhas + notas if "autor" in m.lower()]
        self.assertEqual(sobre_autor, [])

    def test_autor_vazio_sem_a_marca_continua_avisando(self):
        falhas, notas = sapl.preencher(self.pagina, self.form, self._item())
        self.assertTrue(any("autor não identificado" in n for n in notas), notas)


class TestRetomarDeOndeParou(unittest.TestCase):
    """"Parei na 350 e as anteriores eu ja mandei a mao."

    O programa so sabe das indicacoes que ELE cadastrou. Tudo que foi enviado a
    mao - meses de trabalho, num lote que vai da 400 a 301 - e invisivel para
    ele e voltava para a fila em toda sessao: o placar contava errado, e o
    botao "todas" queria dizer "as 400 de novo".
    """

    FILA = [{"numero": n, "ano": 2023} for n in range(400, 300, -1)]

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.arquivo = self.tmp / "enviados.json"

    def test_o_que_vem_antes_e_o_complemento_exato(self):
        """As duas metades nao podem discordar: uma indicacao que fica de fora
        da fila tem de estar na lista das marcadas, e vice-versa."""
        for alvo in (400, 350, 301):
            daqui = sapl.cortar_do_numero(self.FILA, alvo)
            antes = sapl.antes_do_numero(self.FILA, alvo)
            self.assertEqual(len(antes) + len(daqui), len(self.FILA))
            self.assertEqual(antes + daqui, self.FILA)

    def test_lote_decrescente_tira_os_numeros_maiores(self):
        """Na fila de 400 a 301, parar na 350 significa que 400..351 ja foram."""
        antes = sapl.antes_do_numero(self.FILA, 350)
        self.assertEqual(antes[0]["numero"], 400)
        self.assertEqual(antes[-1]["numero"], 351)
        self.assertEqual(len(antes), 50)

    def test_lote_crescente_tira_os_numeros_menores(self):
        """No de 2022, que sobe de 601 a 710, "antes" e o contrario - e por
        isso a regra e por POSICAO na fila, nunca por grandeza do numero."""
        fila = [{"numero": n, "ano": 2022} for n in range(601, 711)]
        antes = sapl.antes_do_numero(fila, 650)
        self.assertEqual(antes[0]["numero"], 601)
        self.assertEqual(antes[-1]["numero"], 649)

    def test_primeira_da_fila_nao_tem_nada_antes(self):
        self.assertEqual(sapl.antes_do_numero(self.FILA, 400), [])

    def test_numero_fora_da_fila_nao_marca_nada(self):
        """Digitar um numero que nao existe nao pode marcar a fila inteira como
        enviada - seria apagar o trabalho todo com um clique."""
        self.assertEqual(sapl.antes_do_numero(self.FILA, 250), [])

    def test_marcar_tira_da_fila_e_registra_como_declarado(self):
        antes = sapl.antes_do_numero(self.FILA, 350)
        mod_enviados.marcar_varias(
            [f"{i['numero']}/{i['ano']}" for i in antes],
            origem=mod_enviados.DECLARADO, caminho=self.arquivo)

        registro = mod_enviados.ler_enviados(self.arquivo)
        self.assertEqual(len(registro), 50)
        self.assertEqual(registro["400/2023"]["origem"], mod_enviados.DECLARADO)
        # E o que interessa: a fila encolhe.
        sobrou = [i for i in self.FILA
                  if f"{i['numero']}/{i['ano']}" not in registro]
        self.assertEqual(len(sobrou), 50)
        self.assertEqual(sobrou[0]["numero"], 350)

    def test_marcar_nao_rebaixa_o_que_o_programa_cadastrou(self):
        """A 380 o programa cadastrou e conferiu na tela. Marcar "ja enviei ate
        a 350" passa por cima dela - e nao pode apagar essa prova."""
        mod_enviados.registrar_envio("380/2023", url="http://x/materia/9",
                                     caminho=self.arquivo)
        mod_enviados.marcar_varias(
            [f"{i['numero']}/{i['ano']}" for i in sapl.antes_do_numero(self.FILA, 350)],
            origem=mod_enviados.DECLARADO, caminho=self.arquivo)

        guardado = mod_enviados.ler_enviados(self.arquivo)["380/2023"]
        self.assertEqual(guardado["origem"], mod_enviados.AUTOMATICO)
        self.assertEqual(guardado["url"], "http://x/materia/9")

    def test_desfazer_devolve_para_a_fila(self):
        """Um clique que tira 50 indicacoes da fila precisa de volta."""
        chaves = [f"{i['numero']}/{i['ano']}"
                  for i in sapl.antes_do_numero(self.FILA, 350)]
        mod_enviados.marcar_varias(chaves, origem=mod_enviados.DECLARADO,
                                   caminho=self.arquivo)

        tirados = mod_enviados.esquecer(chaves, caminho=self.arquivo)

        self.assertEqual(tirados, 50)
        self.assertEqual(mod_enviados.ler_enviados(self.arquivo), {})

    def test_uma_gravacao_so_para_o_lote_inteiro(self):
        """Marcar 50 uma a uma reescreveria o arquivo 50 vezes; uma queda no
        meio deixaria o registro pela metade, sem ninguem saber onde parou."""
        chaves = [f"{i['numero']}/{i['ano']}"
                  for i in sapl.antes_do_numero(self.FILA, 350)]
        registros = mod_enviados.marcar_varias(
            chaves, origem=mod_enviados.DECLARADO, caminho=self.arquivo)
        self.assertEqual(len(registros), 50)
        # Todas com o mesmo carimbo de hora: prova de que foi uma passada so.
        self.assertEqual(len({r["em"] for r in registros.values()}), 1)


if __name__ == "__main__":
    unittest.main()
