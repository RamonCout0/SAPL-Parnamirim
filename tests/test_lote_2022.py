"""Regressao dos tres defeitos encontrados no lote de 2022.

O lote: TODAS_INDICACOES_ATUALIZADAS@2022_P6_frenteverso.pdf, 230 paginas, 110
indicacoes numeradas de 601 a 710 - a primeira vez que um lote CRESCENTE (e nao
"300 a 201", como o de 2023) passou pelo programa. Foi ele que revelou:

  1. a conferencia voltava sempre para a mesma indicacao, sem saida;
  2. "Começar do número" nao adiantava nada: sempre recomecava na primeira;
  3. duas paginas do arquivo trazem "INDICAÇÃO N° 706/2022" impresso - a
     sequencia vai 706, 707, 706, 709 e o 708 nao aparece em lugar nenhum.
     Nao e erro de leitura, e erro no papel; sem tratamento, a segunda viraria
     cadastro com numero de outra e com o PDF da outra anexado.

    .venv\\Scripts\\python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import pipeline, revisao
from src.pipeline import Indicacao, _marcar_numeros_repetidos, _classificar
from src.revisao import (
    escrever_glossario,
    falta_em,
    ja_revisada,
    ler_correcoes,
    linhas_do_glossario,
    registrar_correcao,
    salvar_correcao,
)
from src.detect import (
    Inicio,
    _passo_da_sequencia,
    inferir_numeros,
    marcar_suspeitos,
)
from src.sapl import cortar_ate_numero, cortar_do_numero

IDS_MINIMOS = {"autores": [{"id": 11, "nome": "Binho de Ambrósio", "parlamentar": True},
                           {"id": 12, "nome": "Eder Queiroz", "parlamentar": True}]}


class ResolvedorFalso:
    """_aplicar_correcoes_manuais so chama aprender(); o resto nao interessa."""

    def aprender(self, *args, **kwargs) -> bool:
        return False


def linha_pendente(numero: str, precisa: str, **extra) -> dict:
    base = {
        "numero": numero, "ano": "2022", "paginas": "1-2",
        "NUMERO_MANUAL": "", "DATA_MANUAL": "", "EMENTA_MANUAL": "",
        "AUTOR_ID_MANUAL": "", "CONFIRMAR": "", "precisa": precisa,
        "motivo": "", "data_lida_pela_maquina": "",
        "autor_lido_pela_maquina": "", "sugestao_ollama_autor": "",
        "ementa_lida_pela_maquina": "", "sugestao_ollama_ementa": "",
        "imagens": "",
    }
    base.update(extra)
    return base


class TestConfirmarONumeroLido(unittest.TestCase):
    """Defeito 1: "ele sempre voltava para a mesma indicação".

    A tela pede o numero, a pessoa olha a imagem, ve que o numero lido esta
    CERTO e salva sem mudar nada. Antes isso nao gravava resposta nenhuma: a
    linha continuava faltando "numero", e como a tela sempre volta para a
    primeira pendente, a pessoa era jogada de volta ali a cada salvada.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.glossario = self.tmp / "glossario.csv"
        self.correcoes = self.tmp / "correcoes.json"
        self._original = revisao.CORRECOES
        revisao.CORRECOES = self.correcoes

    def tearDown(self):
        revisao.CORRECOES = self._original

    def test_numero_confirmado_resolve_a_linha(self):
        escrever_glossario(
            [linha_pendente("511", "numero, data")], self.glossario)

        salvar_correcao(self.glossario, "511", "2022",
                        numero_manual="511", data="16/12/2022")

        linha = linhas_do_glossario(self.glossario)[0]
        self.assertEqual(falta_em(linha), [])
        self.assertTrue(ja_revisada(linha))

    def test_numero_confirmado_vira_confirmado_no_json(self):
        """Nao basta sair da fila da tela: o pipeline tem de parar de mandar
        essa indicacao para revisao na rodada seguinte."""
        escrever_glossario(
            [linha_pendente("511", "numero, data")], self.glossario)

        salvar_correcao(self.glossario, "511", "2022",
                        numero_manual="511", data="16/12/2022")

        guardado = ler_correcoes(self.correcoes)["511/2022"]
        self.assertTrue(guardado.get("confirmado"))
        # Confirmar nao e corrigir: nao inventa uma troca de numero que nao
        # houve, senao _renomear_pdfs_corrigidos mexeria em arquivo a toa.
        self.assertNotIn("numero", guardado)

    def test_numero_trocado_continua_sendo_correcao(self):
        escrever_glossario(
            [linha_pendente("9", "numero, data")], self.glossario)

        salvar_correcao(self.glossario, "9", "2022",
                        numero_manual="1629", data="16/12/2022")

        guardado = ler_correcoes(self.correcoes)["9/2022"]
        self.assertEqual(guardado["numero"], 1629)
        self.assertTrue(ja_revisada(linhas_do_glossario(self.glossario)[0]))

    def test_digitar_o_numero_onde_ele_nao_foi_perguntado_nao_confirma_nada(self):
        """A caixa "ja conferi" resolve numero deduzido, pagina unica etc. Ela
        nao pode ser marcada por tabela so porque o campo de numero foi
        submetido com o valor que ja estava la."""
        escrever_glossario(
            [linha_pendente("511", "ementa, confirmar")], self.glossario)

        salvar_correcao(self.glossario, "511", "2022",
                        numero_manual="511", ementa="UMA EMENTA QUALQUER")

        guardado = ler_correcoes(self.correcoes)["511/2022"]
        self.assertNotIn("confirmado", guardado)
        self.assertFalse(ja_revisada(linhas_do_glossario(self.glossario)[0]))


class TestComecarDoNumero(unittest.TestCase):
    """Defeito 2: em lote crescente, "Começar do número" nao saia do lugar."""

    CRESCENTE = [{"numero": n, "ano": 2022} for n in range(601, 611)]
    DECRESCENTE = [{"numero": n, "ano": 2023} for n in range(300, 290, -1)]

    def test_lote_crescente_comeca_no_numero_pedido(self):
        fila = cortar_do_numero(self.CRESCENTE, 605)
        self.assertEqual(fila[0]["numero"], 605)
        self.assertEqual(len(fila), 6)

    def test_lote_decrescente_continua_funcionando(self):
        """O de 2023 vinha de tras para frente e ja funcionava - o conserto
        nao pode quebrar o caso que estava certo."""
        fila = cortar_do_numero(self.DECRESCENTE, 296)
        self.assertEqual(fila[0]["numero"], 296)
        self.assertEqual(len(fila), 6)

    def test_numero_que_nao_esta_na_fila_cai_no_seguinte(self):
        """Acontece o tempo todo depois de enviar: o numero digitado ja saiu da
        fila. Comecar no proximo e o que a pessoa espera."""
        sem_605 = [i for i in self.CRESCENTE if i["numero"] != 605]
        fila = cortar_do_numero(sem_605, 605)
        self.assertEqual(fila[0]["numero"], 606)

    def test_numero_depois_do_fim_da_fila_devolve_vazio(self):
        """Vazio e o sinal de "nao achei" - a tela avisa e comeca do topo, em
        vez de fingir que entendeu."""
        self.assertEqual(cortar_do_numero(self.CRESCENTE, 999), [])

    def test_primeira_da_lista(self):
        self.assertEqual(len(cortar_do_numero(self.CRESCENTE, 601)), 10)

    def test_ate_o_numero_nos_dois_sentidos(self):
        """"--ate 610" num lote que sobe pega as dez primeiras; "--ate 296" num
        que desce pega as cinco primeiras. Antes, "numero >= ate" combinado com
        "numero <= de" devolvia lista VAZIA em lote crescente."""
        subindo = cortar_ate_numero(self.CRESCENTE, 605)
        self.assertEqual([i["numero"] for i in subindo],
                         [601, 602, 603, 604, 605])

        descendo = cortar_ate_numero(self.DECRESCENTE, 296)
        self.assertEqual([i["numero"] for i in descendo],
                         [300, 299, 298, 297, 296])

    def test_de_e_ate_juntos_recortam_um_trecho(self):
        trecho = cortar_ate_numero(cortar_do_numero(self.CRESCENTE, 603), 606)
        self.assertEqual([i["numero"] for i in trecho], [603, 604, 605, 606])


class TestSequenciaNosDoisSentidos(unittest.TestCase):
    """A deteccao de numero nao pode supor que o lote desce.

    Os dois sentidos existem de verdade: 2023 vem de 300 a 201, 2022 vem de 601
    a 710. O passo e tirado dos proprios numeros, COM SINAL.
    """

    def test_passo_acompanha_o_sentido(self):
        self.assertEqual(_passo_da_sequencia([(0, 601), (1, 602), (2, 603)]), 1)
        self.assertEqual(_passo_da_sequencia([(0, 300), (1, 299), (2, 298)]), -1)

    def _com_buraco(self, numeros):
        inicios = [Inicio(pagina=i * 2 + 1, numero=n, ano=2022,
                          tem_cabecalho=n is not None, tem_estrutura=True)
                   for i, n in enumerate(numeros)]
        return inferir_numeros(marcar_suspeitos(inicios), 2022)

    def test_deduz_o_buraco_em_lote_crescente(self):
        inicios = self._com_buraco([601, 602, None, 604, 605])
        self.assertEqual(inicios[2].numero, 603)

    def test_deduz_o_buraco_em_lote_decrescente(self):
        inicios = self._com_buraco([300, 299, None, 297, 296])
        self.assertEqual(inicios[2].numero, 298)

    def test_numero_destruido_pelo_ocr_e_pego_nos_dois_sentidos(self):
        """O "9" no lugar de 1629 tem de ser acusado suba ou desça o lote."""
        for numeros in ([601, 602, 9, 604, 605], [300, 299, 9, 297, 296]):
            inicios = [Inicio(pagina=i * 2 + 1, numero=n, ano=2022,
                              tem_cabecalho=True, tem_estrutura=True)
                       for i, n in enumerate(numeros)]
            marcar_suspeitos(inicios)
            self.assertEqual([i.numero for i in inicios if i.numero_suspeito],
                             [9], f"falhou em {numeros}")


class TestNumeroRepetidoNoLote(unittest.TestCase):
    """Defeito 3: a 708 lida como 706.

    Duas indicacoes diferentes com o mesmo numero. Sem tratamento, a segunda
    seria cadastrada com o numero da primeira e com o PDF da primeira anexado -
    dois defeitos no acervo de uma vez, nenhum deles visivel na tela.
    """

    def indicacoes(self):
        a = Indicacao(numero=706, numero_lido=706, ano=2022,
                      pagina_inicial=221, pagina_final=222, qtd_paginas=2,
                      ementa="UMA EMENTA SUFICIENTEMENTE LONGA PARA PASSAR NO CRITERIO",
                      autor_id=11, data_apresentacao="16/12/2022", confianca=0.9)
        b = Indicacao(numero=706, numero_lido=706, ano=2022,
                      pagina_inicial=225, pagina_final=226, qtd_paginas=2,
                      ementa="OUTRA EMENTA IGUALMENTE LONGA PARA PASSAR NO CRITERIO",
                      autor_id=12, data_apresentacao="16/12/2022", confianca=0.9)
        return [a, b]

    def test_as_duas_vao_para_conferencia(self):
        """Marcar so a segunda nao resolve: olhando uma so nao da para saber
        qual das duas esta com o numero errado."""
        todas = self.indicacoes()
        _marcar_numeros_repetidos(todas, {id(i): "lote2022.pdf" for i in todas})
        for ind in todas:
            _classificar(ind)
            self.assertEqual(ind.status, "revisao")

    def test_o_que_resolve_e_o_numero_nao_o_ja_conferi(self):
        """Se caisse em "confirmar", marcar a caixinha bastaria e as duas
        seguiriam para o SAPL com o mesmo numero."""
        todas = self.indicacoes()
        _marcar_numeros_repetidos(todas, {id(i): "lote2022.pdf" for i in todas})
        for ind in todas:
            _classificar(ind)
            self.assertIn("numero", ind.falta)

    def test_numero_unico_nao_e_marcado(self):
        todas = self.indicacoes()
        todas[1].numero = todas[1].numero_lido = 708
        _marcar_numeros_repetidos(todas, {id(i): "lote2022.pdf" for i in todas})
        for ind in todas:
            _classificar(ind)
            self.assertEqual(ind.motivos, [])
            self.assertEqual(ind.status, "pronto")

    def test_colisao_resolvida_para_de_aparecer(self):
        """Depois de a pessoa dizer "esta e a 708", nenhuma das duas pode
        continuar sendo cobrada - senao a 706, que ja estava certa, ficaria
        presa na fila para sempre pedindo um numero que ja esta certo."""
        todas = self.indicacoes()
        todas[1].numero = 708          # como fica depois da correcao aplicada
        todas[1].numero_corrigido = True
        _marcar_numeros_repetidos(todas, {id(i): "lote2022.pdf" for i in todas})
        for ind in todas:
            _classificar(ind)
            self.assertEqual(ind.status, "pronto", ind.motivos)

    def test_a_mensagem_diz_as_paginas_das_duas(self):
        """E o unico jeito de a pessoa achar as duas imagens para comparar."""
        todas = self.indicacoes()
        _marcar_numeros_repetidos(todas, {id(i): "lote2022.pdf" for i in todas})
        texto = " ".join(todas[0].motivos)
        self.assertIn("221-222", texto)
        self.assertIn("225-226", texto)


class TestCorrecaoDeUmaNaoCaiNaOutra(unittest.TestCase):
    """A parte invisivel do defeito 3: a memoria das correcoes.

    Enquanto a chave era so "numero/ano", as duas 706 dividiam a mesma entrada
    no correcoes.json. Corrigir "esta aqui é a 708" renumerava TAMBEM a 706 de
    verdade - e o lote terminava com duas 708, uma delas cadastrada em silencio
    porque nada mais reclamava dela.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.glossario = self.tmp / "glossario.csv"
        self.correcoes = self.tmp / "correcoes.json"
        self._original = revisao.CORRECOES
        revisao.CORRECOES = self.correcoes
        escrever_glossario(
            [linha_pendente("706", "numero, data", paginas="221-222"),
             linha_pendente("706", "numero, data", paginas="225-226")],
            self.glossario)

    def tearDown(self):
        revisao.CORRECOES = self._original

    def test_cada_bloco_ganha_a_sua_entrada(self):
        salvar_correcao(self.glossario, "706", "2022", paginas="225-226",
                        numero_manual="708", data="16/12/2022")

        guardadas = ler_correcoes(self.correcoes)
        self.assertEqual(list(guardadas), ["706/2022@225-226"])
        self.assertEqual(guardadas["706/2022@225-226"]["numero"], 708)

    def test_grava_na_linha_certa_do_glossario(self):
        salvar_correcao(self.glossario, "706", "2022", paginas="225-226",
                        numero_manual="708", data="16/12/2022")

        linhas = linhas_do_glossario(self.glossario)
        self.assertEqual(linhas[0]["NUMERO_MANUAL"], "",
                         "escreveu na linha da 706 de verdade")
        self.assertEqual(linhas[1]["NUMERO_MANUAL"], "708")

    def test_a_correcao_so_alcanca_o_bloco_dela(self):
        """A prova final: passar pelo pipeline e ver que a 706 continua 706."""
        salvar_correcao(self.glossario, "706", "2022", paginas="225-226",
                        numero_manual="708", data="16/12/2022")

        a = Indicacao(numero=706, numero_lido=706, ano=2022,
                      pagina_inicial=221, pagina_final=222, qtd_paginas=2)
        b = Indicacao(numero=706, numero_lido=706, ano=2022,
                      pagina_inicial=225, pagina_final=226, qtd_paginas=2)

        original = pipeline.CORRECOES
        pipeline.CORRECOES = self.correcoes
        try:
            pipeline._aplicar_correcoes_manuais([a, b], IDS_MINIMOS, ResolvedorFalso())
        finally:
            pipeline.CORRECOES = original

        self.assertEqual(a.numero, 706)
        self.assertEqual(b.numero, 708)
        self.assertTrue(b.numero_corrigido)
        self.assertFalse(a.numero_corrigido)

    def test_correcao_antiga_de_numero_unico_continua_valendo(self):
        """Compatibilidade: o correcoes.json que o usuario ja tem esta todo em
        chaves "numero/ano". Nenhuma delas pode deixar de ser encontrada."""
        registrar_correcao("1405/2022", ementa="TEXTO ANTIGO JA CORRIGIDO",
                           caminho=self.correcoes)
        ind = Indicacao(numero=1405, numero_lido=1405, ano=2022,
                        pagina_inicial=1, pagina_final=2, qtd_paginas=2)

        original = pipeline.CORRECOES
        pipeline.CORRECOES = self.correcoes
        try:
            pipeline._aplicar_correcoes_manuais([ind], IDS_MINIMOS, ResolvedorFalso())
        finally:
            pipeline.CORRECOES = original

        self.assertEqual(ind.ementa, "TEXTO ANTIGO JA CORRIGIDO")


class TestPdfNaoERoubadoDeOutraIndicacao(unittest.TestCase):
    """O pior efeito do numero repetido: o PDF errado no cadastro oficial.

    Depois de a pessoa corrigir "esta e a 708", a versao antiga renomeava
    706-2022.pdf (que e da 706 DE VERDADE) para 708-2022.pdf. A 706 ficava sem
    PDF e a 708 recebia as paginas da 706.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._original = pipeline.PDFS_DIR
        self._gerados = pipeline.PDFS_GERADOS
        pipeline.PDFS_DIR = self.tmp
        pipeline.PDFS_GERADOS = self.tmp / "pdfs_gerados.json"

    def tearDown(self):
        pipeline.PDFS_DIR = self._original
        pipeline.PDFS_GERADOS = self._gerados

    def test_nao_renomeia_por_cima_do_pdf_de_outra(self):
        (self.tmp / "706-2022.pdf").write_bytes(b"paginas 221-222")
        dona = Indicacao(numero=706, numero_lido=706, ano=2022,
                         pagina_inicial=221, pagina_final=222, qtd_paginas=2)
        corrigida = Indicacao(numero=708, numero_lido=706, ano=2022,
                              pagina_inicial=225, pagina_final=226, qtd_paginas=2,
                              numero_corrigido=True)

        pipeline._renomear_pdfs_corrigidos([dona, corrigida])

        self.assertTrue((self.tmp / "706-2022.pdf").exists(),
                        "a 706 de verdade ficou sem o PDF dela")
        self.assertFalse((self.tmp / "708-2022.pdf").exists(),
                         "a 708 recebeu as paginas da 706")

    def test_renomeia_quando_o_nome_antigo_nao_e_de_ninguem(self):
        """O caso normal (numero lido errado, sem colisao) continua igual."""
        (self.tmp / "9-2021.pdf").write_bytes(b"paginas certas")
        corrigida = Indicacao(numero=1629, numero_lido=9, ano=2021,
                              pagina_inicial=1, pagina_final=2, qtd_paginas=2,
                              numero_corrigido=True)

        pipeline._renomear_pdfs_corrigidos([corrigida])

        self.assertTrue((self.tmp / "1629-2021.pdf").exists())
        self.assertFalse((self.tmp / "9-2021.pdf").exists())


if __name__ == "__main__":
    unittest.main()
