"""A data de apresentacao, lida do papel de cada indicacao.

Todos os textos aqui sao recortes REAIS do OCR dos lotes de 2021 - inclusive
os meses destrocados, que sao a regra e nao a excecao nesses scans.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.datas import achar_datas, achar_pagina_do_carimbo, data_de_apresentacao


class TestAcharOCarimbo(unittest.TestCase):
    """A data que vale e a do carimbo "Lido na Sessão", no verso - e ela e
    escrita a mao. O que a maquina faz e achar a PAGINA do carimbo, para a
    interface mostrar a imagem certa na hora de digitar.

    Todos os textos abaixo sao recortes REAIS do OCR dos lotes de 2021.
    """

    CARIMBOS = [
        "Mesa Diretora | Lido na Sessa© | Data: U ! t 3- | cl_n ~ \"t?r90",
        "Mesa Diretora | Lido spa Sessa® | I ii ii i c p | Secrtáro",
        "CAiil1ARA MUNICIPAL DE PARNAMIRIM | Mesa Diretara | Lido X a SeSSa®",
        "Mesa Dia etora | Lido na Sessao | Data: l t / c j | `' `I c. et2rio",
        "Mesa Diretora | Liao | na Sessa4 | Data: tai | -i O | 91 | Secretaraa",
        "GRs ~~a ~~91l~lCE~°r | Mesa Diretora | Lido na ssãa | Data: 10 I n 5",
        "UM!ClRõ:L C6 PARtdAMiR!!~1 | :N irCtora | Lido rº , Sess | Data: ~' _►'' S",
    ]

    def test_acha_o_carimbo_em_todas_as_formas_que_o_ocr_produz(self):
        for texto in self.CARIMBOS:
            with self.subTest(texto=texto[:40]):
                achada = achar_pagina_do_carimbo(
                    {1: "corpo da indicacao", 2: texto},
                    {1: 900, 2: len(texto)}, 1, 2,
                )
                self.assertEqual(achada, 2, texto)

    def test_nao_confunde_com_a_primeira_pagina(self):
        """A folha da indicacao cita "Secretaria Municipal" no proprio pedido:
        sem comecar da segunda pagina, ela seria lida como o carimbo."""
        primeira = ("INDICA ao Chefe do Executivo, extensivo a Secretaria "
                    "Municipal de Obras Publicas e Saneamento SEMOP, " + "x" * 800)
        achada = achar_pagina_do_carimbo(
            {1: primeira}, {1: len(primeira)}, 1, 1,
        )
        self.assertEqual(achada, 0)

    def test_verso_ilegivel_cai_na_segunda_pagina(self):
        """O verso e uma folha quase vazia e as vezes o OCR nao devolve nem o
        "Lido na Sessão". Mostrar a segunda pagina (onde o carimbo fica na
        quase totalidade dos casos) e melhor do que nao mostrar imagem
        nenhuma - quem confere e a pessoa, olhando."""
        achada = achar_pagina_do_carimbo(
            {1: "primeira", 2: "~ ~ | ~~"}, {1: 900, 2: 8}, 1, 2,
        )
        self.assertEqual(achada, 2)

    def test_bloco_de_uma_pagina_nao_tem_verso(self):
        achada = achar_pagina_do_carimbo({1: "primeira"}, {1: 900}, 1, 1)
        self.assertEqual(achada, 0)

    def test_prefere_o_carimbo_de_verdade_a_posicao(self):
        # Bloco de 3 paginas com o carimbo na terceira: vale a terceira.
        achada = achar_pagina_do_carimbo(
            {1: "primeira", 2: "anexo fotografico " * 40,
             3: "Mesa Diretora | Lido na Sessao | Data: l t"},
            {1: 900, 2: 700, 3: 45}, 1, 3,
        )
        self.assertEqual(achada, 3)

    def test_a_data_manuscrita_nao_e_inventada(self):
        """O ponto que mais importa: diante da letra de mao, a maquina tem de
        devolver NADA. Chutar uma data em documento oficial e pior do que
        deixar a pessoa digitar."""
        for texto in self.CARIMBOS:
            with self.subTest(texto=texto[:40]):
                achada = data_de_apresentacao(texto)
                if achada is not None:
                    self.assertNotEqual(
                        achada.ano, 2021,
                        f"inventou uma data de 2021 a partir de {texto!r}")


class TestMesDestrocadoPeloOCR(unittest.TestCase):
    """"dezembro" saiu do scanner de todas estas formas. Comparar letra a
    letra perderia a maioria das datas do lote."""

    def test_meses_reais_do_lote(self):
        casos = [
            ("Plenario Dr. Mario Medeiros, 16 de dehembro de 2021", "16/12/2021"),
            ("Pi.enario Dr, Mari. Medeiros, 06 de Dezembro de 2021", "06/12/2021"),
            ("Plenario Dr. Mario Medeiros, 07 de Dezeinbro de 2021", "07/12/2021"),
            ("PNenarNo Dr. MarNo Med&ros, 9 de dezernbro de 2021", "09/12/2021"),
            ("G lencirio Dr. Merio Miedleiros, 09 de dezembro de 2021", "09/12/2021"),
        ]
        for texto, esperado in casos:
            with self.subTest(texto=texto[-30:]):
                achada = data_de_apresentacao(texto)
                self.assertIsNotNone(achada, texto)
                self.assertEqual(achada.formatada, esperado)

    def test_todos_os_meses_do_ano(self):
        meses = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
                 "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
        for numero, mes in enumerate(meses, start=1):
            with self.subTest(mes=mes):
                achada = data_de_apresentacao(f"Plenário, 05 de {mes} de 2021")
                self.assertIsNotNone(achada, mes)
                self.assertEqual(achada.mes, numero)

    def test_palavra_que_nao_e_mes_nao_vira_data(self):
        # "05 de acordo com 2021" nao e data nenhuma.
        self.assertIsNone(data_de_apresentacao("conforme 05 de acordo com 2021"))


class TestOrigemDaData(unittest.TestCase):
    """Um documento tem mais de uma data. A do fecho da indicacao e a de
    apresentacao; as outras servem para conferir."""

    def test_prefere_o_fecho_da_indicacao(self):
        texto = (
            "Lido na Sessão do dia 20 de dezembro de 2021.\n"
            "Plenário Dr. Mário Medeiros, 16 de dezembro de 2021.\n"
        )
        achada = data_de_apresentacao(texto)
        self.assertEqual(achada.formatada, "16/12/2021")
        self.assertEqual(achada.origem, "plenario")

    def test_reconhece_as_outras_origens(self):
        texto = ("Lido na Sessão do dia 20 de dezembro de 2021. "
                 "RECEBIDO em 21 de dezembro de 2021.")
        origens = {d.origem for d in achar_datas(texto)}
        self.assertIn("lido em sessao", origens)
        self.assertIn("protocolo", origens)

    def test_data_numerica_tambem_vale(self):
        achada = data_de_apresentacao("Plenário, 16/12/2021")
        self.assertEqual(achada.formatada, "16/12/2021")


class TestDataImplausivel(unittest.TestCase):
    def test_dia_e_mes_fora_da_faixa_sao_descartados(self):
        self.assertIsNone(data_de_apresentacao("Plenário, 45 de dezembro de 2021"))

    def test_ano_absurdo_e_descartado(self):
        self.assertIsNone(data_de_apresentacao("Plenário, 16 de dezembro de 1200"))

    def test_ano_errado_pelo_ocr_e_lido_mas_fica_visivel(self):
        """Caso real: "08/12/2002" numa indicacao de 2021. A data e lida (o
        formato e valido), e quem compara com o ano da indicacao e o pipeline,
        que marca data_suspeita - ver _extrair_um_pdf."""
        achada = data_de_apresentacao("Plenário, 08 de dezembro de 2002")
        self.assertIsNotNone(achada)
        self.assertEqual(achada.ano, 2002)


if __name__ == "__main__":
    unittest.main()
