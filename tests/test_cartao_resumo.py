"""Regressao do cartao-resumo e da juncao manual de blocos.

O CASO REAL (lote 500-401 de 2023, paginas 75 a 77)
---------------------------------------------------
A indicacao 465/2023 ocupa tres paginas: o texto, o verso com o carimbo, e uma
folha de resumo com a foto do problema. O OCR destruiu o cabecalho da primeira
pagina - leu "inCilcação n °. 4bb/L11L3" onde estava "Indicação n° 465/2023".

O estrago em cadeia:

  1. sem numero legivel, a pagina 75 so foi reconhecida como inicio pela
     formula juridica de abertura, e o bloco ficou sem numero;
  2. a deteccao de cartao-resumo comparava o numero da folha com o do inicio
     anterior - e nao havia numero anterior com que comparar;
  3. entao a folha de resumo, que trazia "INDICAÇÃO: 465/2023" em letra limpa,
     virou um bloco proprio: uma pagina so, sem ementa, sem autor;
  4. e o lote terminou com DUAS 465/2023.

O numero certo estava escrito, legivel, na propria folha que o programa jogou
fora - e a indicacao foi para revisao pedindo justamente esse numero.

    .venv\\Scripts\\python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import juncoes
from src.detect import Bloco, Inicio, auditar, classificar_paginas, montar_blocos
from src.textlayer import Pagina

# Trechos reais das paginas 75, 76 e 77 do lote 500-401 de 2023.
PRIMEIRA = (
    "CÂMARA MUNICIPAL DE\nPARNAMIRIM\nA CASA DO POVO\n"
    "inCilcação n °. 4bb/L11L3\n"                     # o OCR destruiu o numero
    "Senhor Presidente,\nSenhores Vereadores,\n"
    "Fativan Alves Moura de Paiva, vereadora com assento nesta egrégia\n"
    "Casa Legislativa, Subscrito na forma regimental em vigência, INDICA, ao "
    "Chefe do Executivo Municipal, Excelentíssimo Senhor Prefeito Rosano "
    "Taveira da Cunha, a recuperação de tampa de esgoto na Rua Padre Oliveira "
    "Rolim, no bairro Liberdade."
)
VERSO = ("CÂMARA MU~lClPAL DE PARNdM!RlM\nesa Dfrebor~\nLkio a Se~s~u\n"
         "Câmara Municipal Parnamirim/RN_Johnat Linhares_Mt. 2297")
CARTAO = (
    "CÂMARA MUNICIPAL DE\nPARNAMIRIM\nA CASA  DO POVO\n"
    "INDICAÇÃO: 465/2023 - 27/03/2023 - CÂMARA MUNICIPAL DE PARNAMIRIM/RN\n"
    "VEREADORA: FATIVAN ALVES MOURA DE PAIVA\n"
    "SOLICITAÇÃO: RECUPERAÇÃO DE TAMPA DE ESGOTO NA RUA PADRE OLIVEIRA ROLIM.\n"
    "BAIRRO: LIBERDADE."
)
# A indicacao seguinte, com o cabecalho intacto. Trocar so os digitos nao
# bastaria: "inCilcação" tambem esta destruido e nao casa com CABECALHO_RE.
SEGUINTE = PRIMEIRA.replace("inCilcação n °. 4bb/L11L3", "Indicação n° 464/2023")
LEGIVEL = PRIMEIRA.replace("inCilcação n °. 4bb/L11L3", "Indicação n° 465/2023")


def paginas(*textos: str) -> list[Pagina]:
    """Paginas numeradas a partir de 75, como no arquivo real.

    densidade nao e passada: e uma propriedade, len(texto). O verso e curto de
    proposito (118 caracteres no arquivo real), que e o que o faz cair abaixo
    de DENSIDADE_MINIMA_INICIO e nao ser lido como comeco de indicacao.
    """
    return [
        Pagina(numero=75 + i, texto_bruto=t, texto=t, via_ocr=False)
        for i, t in enumerate(textos)
    ]


class TestCartaoResumo(unittest.TestCase):

    def test_cartao_nao_abre_bloco_novo(self):
        """O que quebrava: a folha de resumo virava uma indicacao."""
        inicios, _ = classificar_paginas(paginas(PRIMEIRA, VERSO, CARTAO))
        self.assertEqual([i.pagina for i in inicios], [75])

    def test_o_numero_do_cartao_salva_o_bloco(self):
        """O cabecalho da pagina 75 saiu ilegivel, mas o cartao diz 465 em
        letra limpa - e ele pertence a este bloco."""
        inicios, _ = classificar_paginas(paginas(PRIMEIRA, VERSO, CARTAO))
        self.assertEqual(inicios[0].numero, 465)
        self.assertEqual(inicios[0].ano, 2023)
        self.assertEqual(inicios[0].numero_do_cartao, 77)

    def test_numero_lido_no_cartao_nao_conta_como_deduzido(self):
        """Ler o numero numa pagina do proprio bloco e leitura, nao deducao -
        e por isso nao manda a indicacao para revisao pedindo confirmacao."""
        inicios, _ = classificar_paginas(paginas(PRIMEIRA, VERSO, CARTAO))
        self.assertFalse(inicios[0].numero_inferido)

    def test_bloco_fica_com_as_tres_paginas(self):
        """O PDF anexado no SAPL passa a ter a indicacao inteira - texto,
        verso e a folha com a foto - em vez de duas metades."""
        inicios, _ = classificar_paginas(paginas(PRIMEIRA, VERSO, CARTAO))
        blocos = montar_blocos(inicios, total_paginas=77, ano_padrao=2023)
        self.assertEqual(len(blocos), 1)
        self.assertEqual((blocos[0].pagina_inicial, blocos[0].pagina_final), (75, 77))
        self.assertEqual(blocos[0].qtd_paginas, 3)

    def test_a_origem_do_numero_fica_escrita(self):
        """Caminho menos obvio precisa deixar rastro: quem conferir depois tem
        de saber que o numero nao veio do cabecalho."""
        inicios, _ = classificar_paginas(paginas(PRIMEIRA, VERSO, CARTAO))
        blocos = montar_blocos(inicios, total_paginas=77, ano_padrao=2023)
        self.assertTrue(any("cartao-resumo" in a and "77" in a
                            for a in blocos[0].avisos), blocos[0].avisos)

    def test_o_cartao_vira_citacao_e_nao_some_do_relatorio(self):
        inicios, citacoes = classificar_paginas(paginas(PRIMEIRA, VERSO, CARTAO))
        do_cartao = [c for c in citacoes if "cartao-resumo" in c["motivo"]]
        self.assertEqual(len(do_cartao), 1)
        self.assertEqual(do_cartao[0]["pagina"], 77)
        self.assertEqual(do_cartao[0]["numero"], 465)

    def test_indicacao_seguinte_continua_abrindo_bloco(self):
        """A correcao nao pode engolir a indicacao de verdade que vem depois:
        ela tem a formula de abertura, o cartao nao."""
        inicios, _ = classificar_paginas(
            paginas(PRIMEIRA, VERSO, CARTAO, SEGUINTE, VERSO))
        self.assertEqual([i.pagina for i in inicios], [75, 78])
        self.assertEqual(inicios[1].numero, 464)

    def test_cartao_com_numero_igual_ao_anterior_continua_pego(self):
        """O sinal antigo (numero repete o do inicio anterior) segue valendo -
        e a rede para o caso em que o OCR estraga os rotulos do cartao."""
        cartao_sem_rotulo = CARTAO.replace("SOLICITAÇÃO:", "S0LIC1TAC~O")
        inicios, _ = classificar_paginas(
            paginas(LEGIVEL, VERSO, cartao_sem_rotulo))
        self.assertEqual([i.pagina for i in inicios], [75])

    def test_sem_cartao_nada_muda(self):
        """Indicacao comum, de duas paginas: continua exatamente como era."""
        inicios, _ = classificar_paginas(paginas(LEGIVEL, VERSO))
        self.assertEqual(len(inicios), 1)
        self.assertEqual(inicios[0].numero, 465)
        self.assertEqual(inicios[0].numero_do_cartao, 0)


class TestJuncaoManual(unittest.TestCase):
    """A saida de emergencia: quando a maquina parte uma indicacao em duas e
    nenhuma regra automatica pega, voce manda juntar na tela de conferencia."""

    def setUp(self):
        self.arquivo = Path(tempfile.mkdtemp()) / "juncoes.json"

    def _inicios(self):
        return [Inicio(pagina=p, numero=n, ano=2023,
                       tem_cabecalho=True, tem_estrutura=True)
                for p, n in ((10, 421), (12, 420), (13, 0), (14, 419))]

    def test_arquivo_inexistente_nao_junta_nada(self):
        inicios = self._inicios()
        self.assertEqual(juncoes.aplicar(inicios, "lote.pdf", self.arquivo),
                         inicios)

    def test_juntar_tira_o_inicio_da_lista(self):
        """A pagina 13 deixa de abrir bloco: as paginas dela passam para o
        bloco que comeca na 12."""
        juncoes.juntar("lote.pdf", 13, self.arquivo)
        restantes = juncoes.aplicar(self._inicios(), "lote.pdf", self.arquivo)
        self.assertEqual([i.pagina for i in restantes], [10, 12, 14])

    def test_juncao_e_por_arquivo(self):
        """Pagina 13 de um lote nao tem nada a ver com a pagina 13 de outro."""
        juncoes.juntar("lote.pdf", 13, self.arquivo)
        restantes = juncoes.aplicar(self._inicios(), "outro.pdf", self.arquivo)
        self.assertEqual(len(restantes), 4)

    def test_nunca_remove_o_primeiro_inicio(self):
        """Nao ha bloco anterior para receber as paginas: junta-lo faria as
        primeiras paginas do arquivo sumirem do lote inteiro."""
        juncoes.juntar("lote.pdf", 10, self.arquivo)
        restantes = juncoes.aplicar(self._inicios(), "lote.pdf", self.arquivo)
        self.assertEqual(restantes[0].pagina, 10)

    def test_separar_desfaz(self):
        juncoes.juntar("lote.pdf", 13, self.arquivo)
        self.assertTrue(juncoes.separar("lote.pdf", 13, self.arquivo))
        restantes = juncoes.aplicar(self._inicios(), "lote.pdf", self.arquivo)
        self.assertEqual(len(restantes), 4)

    def test_separar_o_que_nao_estava_junto(self):
        self.assertFalse(juncoes.separar("lote.pdf", 99, self.arquivo))

    def test_juntar_duas_vezes_nao_duplica(self):
        juncoes.juntar("lote.pdf", 13, self.arquivo)
        juncoes.juntar("lote.pdf", 13, self.arquivo)
        self.assertEqual(juncoes.ler_juncoes(self.arquivo)["lote.pdf"], [13])

    def test_arquivo_corrompido_levanta_erro(self):
        """Devolver vazio aqui desfaria em silencio todas as juncoes feitas."""
        self.arquivo.write_text("{ nao e json", encoding="utf-8")
        with self.assertRaises(ValueError):
            juncoes.ler_juncoes(self.arquivo)


class TestCorteManual(unittest.TestCase):
    """O erro oposto ao da juncao, e o unico daqui que ninguem descobre depois.

    O CASO REAL: a 610 engoliu a 609. O cabecalho da 609 saiu ilegivel e a
    formula juridica de abertura tambem nao pegou, entao a maquina nao abriu
    bloco nenhum ali - as paginas das duas viraram um bloco so, com o numero da
    610. Duas coisas erradas de uma vez:

      - o PDF anexado no SAPL como sendo a 610 leva dentro o documento da 609;
      - a 609 nao existe em lugar nenhum do lote. Nao da erro, nao entra na
        fila, nao aparece na revisao: simplesmente nao foi criada.

    Na tela de conferencia voce olha as imagens, ve onde a segunda comeca e
    manda separar, informando o numero que esta escrito no papel.
    """

    def setUp(self):
        self.arquivo = Path(tempfile.mkdtemp()) / "juncoes.json"

    def _inicios(self):
        """Como o detector devolveu o lote: a 609 nao esta aqui. O bloco da 610
        comeca na pagina 20 e vai ate a 23, porque a 608 so comeca na 24."""
        return [Inicio(pagina=p, numero=n, ano=2023,
                       tem_cabecalho=True, tem_estrutura=True)
                for p, n in ((18, 611), (20, 610), (24, 608))]

    def test_corte_insere_o_inicio_que_faltava(self):
        juncoes.cortar("lote.pdf", 22, 609, self.arquivo)
        restantes = juncoes.aplicar(self._inicios(), "lote.pdf", self.arquivo)
        self.assertEqual([i.pagina for i in restantes], [18, 20, 22, 24])
        self.assertEqual([i.numero for i in restantes], [611, 610, 609, 608])

    def test_o_bloco_engolido_vira_bloco_proprio(self):
        """A prova que interessa: depois do corte, cada uma fica com as suas
        paginas - antes a 610 levava as quatro e a 609 nao existia."""
        juncoes.cortar("lote.pdf", 22, 609, self.arquivo)
        inicios = juncoes.aplicar(self._inicios(), "lote.pdf", self.arquivo)
        blocos = montar_blocos(inicios, total_paginas=30, ano_padrao=2023)
        faixas = {b.numero: b.faixa for b in blocos}
        self.assertEqual(faixas[610], "20-21")
        self.assertEqual(faixas[609], "22-23")

    def test_corte_marca_que_a_fronteira_e_humana(self):
        """Quem conferir depois precisa saber que este inicio nao foi lido."""
        juncoes.cortar("lote.pdf", 22, 609, self.arquivo)
        inicios = juncoes.aplicar(self._inicios(), "lote.pdf", self.arquivo)
        novo = next(i for i in inicios if i.pagina == 22)
        self.assertTrue(novo.corte_manual)
        self.assertFalse(novo.tem_cabecalho)
        bloco = next(b for b in montar_blocos(inicios, 30, 2023) if b.numero == 609)
        self.assertTrue(bloco.corte_manual)
        self.assertTrue(any("marcado por voce" in a for a in bloco.avisos))

    def test_o_ano_do_lote_manda_no_bloco_cortado(self):
        """O corte nao guarda ano: guardar um seria mais um numero para digitar
        errado, e o ano do lote ja e conhecido."""
        juncoes.cortar("lote.pdf", 22, 609, self.arquivo)
        inicios = juncoes.aplicar(self._inicios(), "lote.pdf", self.arquivo)
        bloco = next(b for b in montar_blocos(inicios, 30, 2023) if b.numero == 609)
        self.assertEqual(bloco.ano, 2023)
        self.assertEqual(bloco.avisos.count("OCR leu ano 2023; corrigido para 2023"), 0)

    def test_corte_e_por_arquivo(self):
        juncoes.cortar("lote.pdf", 22, 609, self.arquivo)
        restantes = juncoes.aplicar(self._inicios(), "outro.pdf", self.arquivo)
        self.assertEqual(len(restantes), 3)

    def test_corte_em_pagina_que_ja_era_inicio_nao_faz_nada(self):
        """Senao sairiam dois blocos comecando na mesma pagina, um deles sem
        pagina nenhuma dentro."""
        juncoes.cortar("lote.pdf", 20, 610, self.arquivo)
        restantes = juncoes.aplicar(self._inicios(), "lote.pdf", self.arquivo)
        self.assertEqual([i.pagina for i in restantes], [18, 20, 24])

    def test_a_lista_volta_em_ordem_de_pagina(self):
        """montar_blocos fecha cada bloco na pagina anterior a do proximo da
        lista: fora de ordem, um bloco terminaria antes de comecar."""
        juncoes.cortar("lote.pdf", 23, 609, self.arquivo)
        juncoes.cortar("lote.pdf", 19, 611, self.arquivo)
        paginas = [i.pagina for i in
                   juncoes.aplicar(self._inicios(), "lote.pdf", self.arquivo)]
        self.assertEqual(paginas, sorted(paginas))

    def test_cortar_duas_vezes_na_mesma_pagina_nao_duplica(self):
        """A segunda vale: e uma correcao do numero, nao um corte novo."""
        juncoes.cortar("lote.pdf", 22, 609, self.arquivo)
        juncoes.cortar("lote.pdf", 22, 1609, self.arquivo)
        self.assertEqual(juncoes.ler_cortes(self.arquivo)["lote.pdf"],
                         [{"pagina": 22, "numero": 1609}])

    def test_desfazer_corte(self):
        juncoes.cortar("lote.pdf", 22, 609, self.arquivo)
        self.assertTrue(juncoes.desfazer_corte("lote.pdf", 22, self.arquivo))
        self.assertEqual(len(juncoes.aplicar(self._inicios(), "lote.pdf",
                                             self.arquivo)), 3)

    def test_desfazer_o_que_nao_estava_cortado(self):
        self.assertFalse(juncoes.desfazer_corte("lote.pdf", 99, self.arquivo))

    def test_juntar_e_cortar_nao_convivem_na_mesma_pagina(self):
        """Sao ordens opostas. Guardar as duas deixaria o pipeline desempatando
        sozinho; a ultima palavra e a de quem marcou por ultimo."""
        juncoes.cortar("lote.pdf", 22, 609, self.arquivo)
        juncoes.juntar("lote.pdf", 22, self.arquivo)
        self.assertEqual(juncoes.ler_cortes(self.arquivo).get("lote.pdf", []), [])
        self.assertEqual(juncoes.ler_juncoes(self.arquivo)["lote.pdf"], [22])

        juncoes.cortar("lote.pdf", 22, 609, self.arquivo)
        self.assertEqual(juncoes.ler_juncoes(self.arquivo).get("lote.pdf", []), [])

    def test_juncao_e_corte_no_mesmo_arquivo(self):
        """As duas marcacoes convivem no mesmo lote - so nao na mesma pagina."""
        juncoes.juntar("lote.pdf", 24, self.arquivo)
        juncoes.cortar("lote.pdf", 22, 609, self.arquivo)
        paginas = [i.pagina for i in
                   juncoes.aplicar(self._inicios(), "lote.pdf", self.arquivo)]
        self.assertEqual(paginas, [18, 20, 22])

    def test_arquivo_corrompido_levanta_erro(self):
        self.arquivo.write_text("{ nao e json", encoding="utf-8")
        with self.assertRaises(ValueError):
            juncoes.ler_cortes(self.arquivo)


class TestSuspeitaDeBlocoDuplo(unittest.TestCase):
    """O aviso que faz o bloco engolido chegar na tela de conferencia.

    Sem ele o botao de separar nunca seria usado, porque a indicacao engolida
    nao reclama de nada: o bloco sai com ementa e autor legiveis, e vai para o
    SAPL classificado como PRONTO.
    """

    @staticmethod
    def _blocos(tamanhos: list[tuple[int, int]]) -> list[Bloco]:
        """[(numero, qtd_paginas)] em sequencia, ocupando paginas seguidas."""
        blocos = []
        pagina = 1
        for numero, qtd in tamanhos:
            blocos.append(Bloco(numero=numero, ano=2023, pagina_inicial=pagina,
                                pagina_final=pagina + qtd - 1))
            pagina += qtd
        return blocos

    def test_bloco_do_dobro_do_tamanho_antes_de_um_buraco(self):
        """O caso da 610: pulo na sequencia E o dobro das paginas."""
        blocos = auditar(self._blocos(
            [(612, 2), (611, 2), (610, 4), (608, 2), (607, 2)]))
        engoliu = {b.numero: b.engoliu for b in blocos}
        self.assertEqual(engoliu[610], [609])
        self.assertTrue(any("609" in a for a in
                            next(b for b in blocos if b.numero == 610).avisos))

    def test_buraco_com_bloco_de_tamanho_normal_nao_acusa(self):
        """Indicacao que simplesmente nao foi escaneada. Acusar todo pulo
        mandaria dezenas de blocos corretos para a conferencia."""
        blocos = auditar(self._blocos(
            [(612, 2), (611, 2), (610, 2), (608, 2), (607, 2)]))
        self.assertEqual([b.engoliu for b in blocos], [[], [], [], [], []])

    def test_bloco_grande_sem_buraco_na_sequencia_nao_acusa(self):
        """Anexo fotografico engorda bloco sem esconder nada - e ja tem o aviso
        de "conferir se falta um inicio" so pelo tamanho."""
        blocos = auditar(self._blocos(
            [(612, 2), (611, 2), (610, 5), (609, 2), (608, 2)]))
        self.assertEqual([b.engoliu for b in blocos], [[], [], [], [], []])

    def test_sequencia_crescente(self):
        """O lote de 2022 sobe (601 -> 710). O sentido sai dos numeros."""
        blocos = auditar(self._blocos(
            [(605, 2), (606, 2), (607, 4), (609, 2), (610, 2)]))
        self.assertEqual(next(b for b in blocos if b.numero == 607).engoliu, [608])

    def test_o_corte_fecha_o_buraco_e_o_aviso_some(self):
        """O ciclo inteiro: a maquina acusa, voce corta, e na rodada seguinte
        nao ha mais nada a acusar - senao o aviso ficaria para sempre e voce
        cortaria de novo, achando que a marcacao nao pegou."""
        arquivo = Path(tempfile.mkdtemp()) / "juncoes.json"
        # Como a maquina leu: a 609 nao virou inicio, entao o bloco da 610 vai
        # da pagina 20 a 23 (a 608 so comeca na 24).
        inicios = [Inicio(pagina=p, numero=n, ano=2023,
                          tem_cabecalho=True, tem_estrutura=True)
                   for p, n in ((16, 612), (18, 611), (20, 610), (24, 608),
                                (26, 607))]

        antes = auditar(montar_blocos(inicios, 27, 2023))
        self.assertEqual(next(b for b in antes if b.numero == 610).engoliu, [609])

        juncoes.cortar("lote.pdf", 22, 609, arquivo)
        depois = auditar(montar_blocos(
            juncoes.aplicar(inicios, "lote.pdf", arquivo), 27, 2023))
        self.assertEqual([b.engoliu for b in depois], [[], [], [], [], [], []])
        self.assertEqual([b.numero for b in depois],
                         [612, 611, 610, 609, 608, 607])

    def test_virada_de_sequencia_nao_acusa(self):
        """O lote real de 2021 vira: ...792, 793, depois 601, 602. Um bloco nao
        engoliu 192 indicacoes - listar todas seria um aviso ilegivel."""
        blocos = auditar(self._blocos(
            [(791, 2), (792, 2), (793, 6), (601, 2), (602, 2)]))
        self.assertEqual(next(b for b in blocos if b.numero == 793).engoliu, [])


if __name__ == "__main__":
    unittest.main()
