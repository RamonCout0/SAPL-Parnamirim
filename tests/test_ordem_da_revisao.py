"""A conferencia anda em ordem de indicacao, nao na ordem em que os PDFs foram
varridos.

A varredura entrega 2023 embaralhado por dois motivos que nada tem a ver com o
acervo: os arquivos entram por NOME (o "2030_A_1901" vem antes do "1000_A_901"
so porque tem um espaco onde o outro tem "_") e dentro de varios deles a
numeracao DESCE. Medido no glossario real: 95 quebras de sequencia em 1849
linhas - abria na 1901, subia ate a 2030, caia na 985, descia ate a 901,
pulava para a 1001.

Quem confere le o PAPEL e procura o numero. Saltar de centena em centena a cada
tela cobra reencontrar o lugar no maco a cada indicacao.

O que se testa aqui:

  - a ordem sai crescente por ano e numero, com os dois sentidos de lote e os
    varios arquivos misturados;
  - um numero corrigido a mao manda na ordem (a 1958 lida como 158 deixa de
    ficar sozinha la em cima);
  - linhas com o MESMO numero lido nao se embaralham entre si - e (arquivo,
    pagina) que as separa no resto do programa, inclusive na juncao;
  - ordenar nao perde nem inventa linha.

    .venv\\Scripts\\python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.revisao import chave_de_ordem, ordenar_glossario


def linha(numero, *, ano="2023", paginas="1-2", arquivo="lote.pdf",
          numero_manual=""):
    return {"numero": str(numero), "ano": ano, "paginas": paginas,
            "arquivo": arquivo, "NUMERO_MANUAL": numero_manual}


def numeros(linhas):
    brutos = [str(l["NUMERO_MANUAL"] or l["numero"]) for l in linhas]
    return [int(b) if b.isdigit() else b for b in brutos]


class TestOrdemDaRevisao(unittest.TestCase):

    def test_lote_decrescente_vira_crescente(self):
        """O 2030_A_1901: no papel desce, na conferencia sobe."""
        cru = [linha(n, paginas=f"{i*2+1}-{i*2+2}")
               for i, n in enumerate(range(2030, 2024, -1))]
        self.assertEqual(numeros(ordenar_glossario(cru)),
                         [2025, 2026, 2027, 2028, 2029, 2030])

    def test_arquivos_diferentes_se_intercalam_pelo_numero(self):
        """O caso real: o 2030_A_1901 e varrido ANTES do 1000_A_901 por causa
        de um espaco no nome do arquivo. A conferencia nao pode herdar isso."""
        cru = ([linha(n, arquivo="2030_A_1901.pdf") for n in (1901, 1902)]
               + [linha(n, arquivo="1000_A_901.pdf") for n in (985, 984)]
               + [linha(n, arquivo="1100_A_1001.pdf") for n in (1001, 1002)])
        self.assertEqual(numeros(ordenar_glossario(cru)),
                         [984, 985, 1001, 1002, 1901, 1902])

    def test_numero_corrigido_manda_na_ordem(self):
        """A 1958 que o OCR leu como 158 fica sozinha no topo ate ser
        corrigida; corrigida, vai para o meio das vizinhas dela."""
        cru = [linha(1957), linha(158, numero_manual="1958"), linha(1959)]
        self.assertEqual(numeros(ordenar_glossario(cru)), [1957, 1958, 1959])

    def test_numero_ilegivel_nao_derruba_a_ordenacao(self):
        """Numero em branco ou com lixo do OCR vai para o comeco em vez de
        estourar - a linha e pendencia, e pendencia tem de aparecer."""
        cru = [linha(902), linha(""), linha("?")]
        self.assertEqual(len(ordenar_glossario(cru)), 3)
        self.assertEqual(numeros(ordenar_glossario(cru))[-1], 902)

    def test_mesmo_numero_lido_fica_separado_por_arquivo_e_pagina(self):
        """Seis numeros aparecem repetidos em 2023, todos por erro de leitura.
        Se essas linhas trocassem de lugar entre si, a correcao digitada numa
        iria parar na outra - e (arquivo, pagina) e exatamente o par que
        salvar_correcao() e src/juncoes.py usam para nao confundi-las."""
        cru = [linha(1968, arquivo="b.pdf", paginas="80-81"),
               linha(1968, arquivo="a.pdf", paginas="40-41"),
               linha(1968, arquivo="a.pdf", paginas="10-11")]
        ordenada = ordenar_glossario(cru)
        self.assertEqual([(l["arquivo"], l["paginas"]) for l in ordenada],
                         [("a.pdf", "10-11"), ("a.pdf", "40-41"),
                          ("b.pdf", "80-81")])

    def test_paginas_ordenam_por_numero_e_nao_por_texto(self):
        """"100-101" vem depois de "9-10". Como texto, viria antes."""
        cru = [linha(700, paginas="100-101"), linha(700, paginas="9-10")]
        self.assertEqual([l["paginas"] for l in ordenar_glossario(cru)],
                         ["9-10", "100-101"])

    def test_anos_diferentes_nao_se_misturam(self):
        cru = [linha(300, ano="2023"), linha(1400, ano="2022")]
        self.assertEqual([l["ano"] for l in ordenar_glossario(cru)],
                         ["2022", "2023"])

    def test_ordenar_nao_perde_nem_inventa_linha(self):
        cru = [linha(n) for n in (5, 3, 9, 1, 3)]
        ordenada = ordenar_glossario(cru)
        self.assertEqual(len(ordenada), len(cru))
        self.assertEqual(sorted(numeros(ordenada)), sorted(numeros(cru)))

    def test_lista_original_fica_intacta(self):
        """A ordem do ARQUIVO nao muda por se ler o glossario: e a ela que
        salvar_correcao() reescreve por cima."""
        cru = [linha(9), linha(1)]
        ordenar_glossario(cru)
        self.assertEqual(numeros(cru), [9, 1])

    def test_chave_aceita_linha_de_versao_antiga(self):
        """Glossario gerado antes de existir a coluna "arquivo" continua
        legivel - sem isso a tela nao abriria."""
        self.assertIsInstance(chave_de_ordem({"numero": "7"}), tuple)

    def test_ordena_a_linha_do_pipeline_com_numero_int(self):
        """A MESMA linha chega aqui em dois formatos: vinda do CSV e tudo
        texto; vinda do pipeline, "numero" e "ano" ainda sao int, porque quem
        os converte e o csv na hora de escrever. Ordenar ANTES de gravar o
        glossario passava por aqui com int e estourava em .strip()."""
        cru = [{"numero": 1902, "ano": 2023, "paginas": "3-4",
                "arquivo": "lote.pdf"},
               {"numero": 1901, "ano": 2023, "paginas": "1-2",
                "arquivo": "lote.pdf"}]
        self.assertEqual([l["numero"] for l in ordenar_glossario(cru)],
                         [1901, 1902])


if __name__ == "__main__":
    unittest.main(verbosity=2)
