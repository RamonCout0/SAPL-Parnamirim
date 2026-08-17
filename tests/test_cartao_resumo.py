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
from src.detect import Inicio, classificar_paginas, montar_blocos
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


if __name__ == "__main__":
    unittest.main()
