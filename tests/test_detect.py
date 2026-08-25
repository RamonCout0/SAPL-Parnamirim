"""Regressao da deteccao de cabecalho.

Roda sem nenhuma dependencia externa:

    .venv\\Scripts\\python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.detect import (
    CABECALHO_RE,
    Inicio,
    classificar_paginas,
    inferir_numeros,
    marcar_suspeitos,
    montar_blocos,
    numero_do_cabecalho,
)
from src.textlayer import Pagina


ABERTURA = (
    "Senhor Presidente,\n"
    "Fulano de Tal Silva, vereador com assento nesta egrégia Casa "
    "Legislativa, subscrito na forma regimental em vigência, INDICA ao "
    "Excelentíssimo Senhor Prefeito a pavimentação da Rua das Flores, no "
    "bairro Nova Parnamirim, atendendo a pedido dos moradores da região que "
    "há anos convivem com a poeira e a lama.\n"
    "Justificativa\n"
) * 2


def pagina(numero: int, texto: str) -> Pagina:
    return Pagina(numero=numero, texto_bruto=texto, texto=texto,
                  linhas=texto.splitlines())


class TestNumeroComSeparador(unittest.TestCase):
    """A partir da indicacao 1000 o papel escreve "n° 1.405/2022".

    A regex antiga exigia digitos colados e o cabecalho inteiro deixava de
    casar - a indicacao caia em "numero deduzido pela sequencia" e ia para
    revisao manual sempre. Estes casos vieram do lote real de 2022.
    """

    def test_ponto_como_separador_de_milhar(self):
        m = CABECALHO_RE.search("INDICAÇÃO n° 1.405/2022")
        self.assertIsNotNone(m, "cabecalho com ponto tem de casar")
        self.assertEqual(numero_do_cabecalho(m.group(1)), 1405)
        self.assertEqual(int(m.group(2)), 2022)

    def test_espaco_como_separador_de_milhar(self):
        m = CABECALHO_RE.search("INDICAÇÃO N.º 1 405/2022")
        self.assertIsNotNone(m)
        self.assertEqual(numero_do_cabecalho(m.group(1)), 1405)

    def test_espaco_antes_da_barra(self):
        m = CABECALHO_RE.search("INDICAÇÃO Nº 1.405 /2022")
        self.assertIsNotNone(m)
        self.assertEqual(numero_do_cabecalho(m.group(1)), 1405)

    def test_sem_separador_continua_valendo(self):
        m = CABECALHO_RE.search("Indicação nº 1405/2022")
        self.assertIsNotNone(m)
        self.assertEqual(numero_do_cabecalho(m.group(1)), 1405)

    def test_numero_de_tres_digitos_nao_regrediu(self):
        m = CABECALHO_RE.search("INDICAÇÃO n° 405/2022")
        self.assertIsNotNone(m)
        self.assertEqual(numero_do_cabecalho(m.group(1)), 405)

    def test_tolerancia_de_ocr_preservada(self):
        # Erros reais do scan: "Indicaçno", "n'", ano com espaco.
        for texto, esperado in [
            ("Indicaçno n° 1.296/2023", 1296),
            ("Indicação n' 294/ 2022", 294),
            ("INDICACAO No 1.001-2022", 1001),
        ]:
            with self.subTest(texto=texto):
                m = CABECALHO_RE.search(texto)
                self.assertIsNotNone(m, texto)
                self.assertEqual(numero_do_cabecalho(m.group(1)), esperado)


class TestNumeroNaoEDeduzido(unittest.TestCase):
    """O efeito em cascata: com o cabecalho ilegivel o numero saia deduzido
    pela sequencia, e "numero deduzido" forca revisao manual."""

    def test_pagina_com_numero_de_quatro_digitos_e_lida_do_papel(self):
        paginas = [
            pagina(1, "INDICAÇÃO n° 1.405/2022\n" + ABERTURA),
            pagina(2, "Lido na Sessão. Mesa Diretora."),
            pagina(3, "INDICAÇÃO n° 1.404/2022\n" + ABERTURA),
            pagina(4, "Lido na Sessão. Mesa Diretora."),
        ]
        inicios, _ = classificar_paginas(paginas)
        blocos = montar_blocos(inicios, len(paginas), 2022)

        self.assertEqual([b.numero for b in blocos], [1405, 1404])
        for b in blocos:
            self.assertFalse(
                b.numero_inferido,
                f"{b.identificador} nao devia depender de deducao",
            )

    def test_citacao_no_corpo_nao_abre_bloco(self):
        # "REITERA a indicação n° 1.498/2022" no meio do texto e citacao, nao
        # cabecalho: continua valendo so o primeiro cabecalho da pagina.
        texto = (
            "INDICAÇÃO n° 1.405/2022\n" + ABERTURA
            + "\nREITERA a indicação n° 1.498/2022 apresentada anteriormente.\n"
        )
        inicios, citacoes = classificar_paginas([pagina(1, texto)])
        self.assertEqual([i.numero for i in inicios], [1405])
        self.assertIn(1498, [c["numero"] for c in citacoes])


# A folha real que fez a indicacao 987 desaparecer do lote 1000-901 de 2023.
# Tudo aqui e copia do texto que o OCR devolveu, quebras de linha inclusive:
#
#   - "987 12023" - a barra do "987/2023" foi lida como o algarismo 1;
#   - "subscrito na forma\nregimental" - a quebra parte o marcador ao meio;
#   - "Casa Legislativa" comeca no caractere 270, quase encostado no limite de
#     280 da janela, e termina depois dele.
#
# Os tres juntos derrubaram os DOIS sinais de deteccao na mesma pagina: ela nao
# abriu bloco, as folhas foram parar dentro da indicacao anterior e a 987 nao
# existiu em lugar nenhum - nem no lote, nem numa lista de erro.
MODELO_INDICACAO_N = (
    "INDICAÇÃO N°. {numero} 1{ano}\n"
    "Sr. Presidente,\n"
    "Nobres Vereadores,\n"
    "PARNAM PRIM\n"
    "O Vereador Lindovaildo Soares de Azevedo — VAVÁ AZEVEDO, subscrito na forma\n"
    "regimental em vigência, no uso de suas atribuições legais, com fundamento "
    "no Artigo 148 do\n"
    "Regimento Interno desta Egrégia Casa Legislativa, VEM INDICAR ao Chefe do "
    "Poder Executivo\n"
    "Municipal (Exmo. Sr. Prefeito Rosano Taveira da Cunha), extensivo à "
    "Secretaria Municipal de\n"
    "Obras Públicas e Saneamento (SEMOP), a adoção de providências de modo a "
    "realizar OBRAS DE\n"
    "PAVIMENTAÇÃO na Rua Caminho do Sol, Bairro de Cajupiranga, neste "
    "Município.\n"
    "Justificativa\n"
    "Atendendo aos anseios da população, e constatada a necessidade do "
    "serviço, solicitamos as\n"
    "providencias cabiveis para o atendimento do pleito ora apresentado.\n"
)


class TestBarraLidaComoUm(unittest.TestCase):
    """O OCR le a barra do cabecalho como o algarismo 1 e cola no ano.

    Casos reais do lote 1000-901/2023: "987 12023", "989 12023", "992 12023".
    Sem casar o cabecalho, o numero ou saia deduzido pela sequencia ou - pior -
    saia de um pedaco solto do texto: a 992 foi cadastrada como "18/2023".
    """

    def test_barra_virou_algarismo_um(self):
        m = CABECALHO_RE.search("INDICAÇÃO N°. 987 12023")
        self.assertIsNotNone(m, "o cabecalho com a barra lida como 1 tem de casar")
        self.assertEqual(numero_do_cabecalho(m.group(1)), 987)
        self.assertEqual(int(m.group(2)), 2023)

    def test_barra_virou_um_sem_espaco_nenhum(self):
        # "ão n° 92112023." - sai colado, e o numero certo e o mais longo.
        m = CABECALHO_RE.search("Indicação n° 92112023")
        self.assertIsNotNone(m)
        self.assertEqual(numero_do_cabecalho(m.group(1)), 921)

    def test_barra_virou_exclamacao(self):
        # "INDICAÇÃO N°. 929 ! 2023". Sem casar aqui, a leitura caia numa
        # sobra de numero mais adiante na pagina e a 929 virava "385/2023" -
        # numero de outro lote, com correcao manual ja gravada no nome dele.
        m = CABECALHO_RE.search("INDICAÇÃO N°. 929 ! 2023")
        self.assertIsNotNone(m)
        self.assertEqual(numero_do_cabecalho(m.group(1)), 929)

    def test_barra_de_verdade_continua_ganhando(self):
        # A barra existe: nada de ler "1405" como "140" + separador "5".
        for texto, esperado in [
            ("INDICAÇÃO n° 1.405/2022", 1405),
            ("Indicação nº 1405/2022", 1405),
            ("INDICAÇÃO n° 405/2022", 405),
        ]:
            with self.subTest(texto=texto):
                m = CABECALHO_RE.search(texto)
                self.assertEqual(numero_do_cabecalho(m.group(1)), esperado)


class TestPaginaNaoDesaparece(unittest.TestCase):
    """A regressao inteira, do jeito que ela apareceu no papel."""

    def test_folha_do_modelo_indicacao_n_abre_bloco(self):
        paginas = [
            pagina(1, MODELO_INDICACAO_N.format(numero=988, ano=2023)),
            pagina(2, "Mesa Diretora\nLido na Sessã\nData: ,\n1 0 Secret"),
            pagina(3, MODELO_INDICACAO_N.format(numero=987, ano=2023)),
            pagina(4, "Mesa, Diretora\nLido na Sess o\nData: ,\n1° sec.-tátio"),
        ]
        inicios, _ = classificar_paginas(paginas)
        self.assertEqual([i.pagina for i in inicios], [1, 3],
                         "as duas folhas de rosto tem de abrir bloco")
        self.assertEqual([i.numero for i in inicios], [988, 987])
        for i in inicios:
            self.assertFalse(i.numero_inferido)

        blocos = montar_blocos(inicios, len(paginas), 2023)
        self.assertEqual([(b.numero, b.pagina_inicial, b.pagina_final)
                          for b in blocos],
                         [(988, 1, 2), (987, 3, 4)],
                         "cada indicacao com as suas duas paginas")

    def test_marcador_partido_pela_quebra_de_linha_ainda_conta(self):
        # So o segundo sinal, sem numero nenhum: mesmo assim tem de abrir bloco.
        texto = MODELO_INDICACAO_N.format(numero=987, ano=2023).replace(
            "INDICAÇÃO N°. 987 12023\n", "")
        inicios, _ = classificar_paginas([pagina(1, texto)])
        self.assertEqual(len(inicios), 1,
                         '"subscrito na forma\\nregimental" e formula de abertura')
        self.assertTrue(inicios[0].tem_estrutura)

    def test_casa_legislativa_no_corpo_continua_sem_abrir_bloco(self):
        # O motivo de a janela ser curta: "casa legislativa" tambem aparece na
        # justificativa, bem mais tarde. Continuacao nao pode virar inicio.
        texto = (
            "documento em que os moradores relatam a situacao da via, com "
            "fotografias anexas que mostram o estado do calcamento e o "
            "acumulo de agua parada em frente as residencias, problema que se "
            "arrasta ha anos sem qualquer providencia do poder publico "
            "municipal, razao pela qual pedimos que esta Casa Legislativa "
            "de inicio ao debate.\n"
        )
        inicios, _ = classificar_paginas([pagina(1, texto)])
        self.assertEqual(inicios, [])


def inicio(pagina: int, numero: int | None, inferido: bool = False) -> Inicio:
    return Inicio(pagina=pagina, numero=numero, ano=2021, tem_cabecalho=numero is not None,
                  tem_estrutura=True, numero_inferido=inferido)


class TestNumeroForaDaSequencia(unittest.TestCase):
    """Casos REAIS do lote de 2021, onde o OCR destruiu o cabecalho:

        pagina 18  "Indicacao n° /617/2021"      -> leu 617, era 1617
        pagina 45  "INDICAcAO N°. iG l9 / 2021"  -> leu 9,   era 1629

    O da pagina 45 tinha ementa e autor bons e foi classificado como PRONTO:
    iria para o SAPL como "Indicacao 9/2021", registro oficial errado.
    """

    def test_numero_absurdo_e_marcado(self):
        inicios = marcar_suspeitos([
            inicio(1, 1628), inicio(3, 9), inicio(5, 1630), inicio(7, 1631),
        ])
        self.assertTrue(inicios[1].numero_suspeito, "o 9 tem de acusar")
        self.assertFalse(any(i.numero_suspeito for i in inicios if i.numero != 9))

    def test_digito_perdido_e_marcado(self):
        inicios = marcar_suspeitos([
            inicio(1, 1615), inicio(3, 617), inicio(5, 1618), inicio(7, 1619),
        ])
        self.assertTrue(inicios[1].numero_suspeito)

    def test_buraco_normal_na_sequencia_nao_acusa(self):
        # Indicacoes que simplesmente nao estao no lote: 1646 -> 1650.
        inicios = marcar_suspeitos([
            inicio(1, 1643), inicio(3, 1645), inicio(5, 1646),
            inicio(7, 1650), inicio(9, 1652), inicio(11, 1653),
        ])
        self.assertEqual([i.numero for i in inicios if i.numero_suspeito], [])

    def test_virada_legitima_de_sequencia_nao_acusa(self):
        # O lote real de 2021 tem uma: ...792, 793, depois 601, 602...
        # Cada um concorda com o proprio lado, entao nenhum e suspeito.
        inicios = marcar_suspeitos([
            inicio(1, 791), inicio(3, 792), inicio(5, 793),
            inicio(7, 601), inicio(9, 602), inicio(11, 603),
        ])
        self.assertEqual([i.numero for i in inicios if i.numero_suspeito], [])

    def test_suspeito_nao_serve_de_ancora_para_deducao(self):
        """O erro que gerou outro erro: o "9" virou ancora e a vizinha, cujo
        cabecalho o OCR perdeu de vez, foi deduzida como "10" em vez de 1630."""
        inicios = inferir_numeros(marcar_suspeitos([
            inicio(1, 1627), inicio(3, 1628), inicio(5, 9),
            inicio(7, None), inicio(9, 1631), inicio(11, 1632),
        ]), 2021)
        deduzida = inicios[3]
        self.assertTrue(deduzida.numero_inferido)
        self.assertEqual(deduzida.numero, 1630,
                         "devia se ancorar nas vizinhas boas, nao no 9")

    def test_sequencia_curta_nao_acusa_nada(self):
        # Com duas indicacoes nao da para saber o que e desvio.
        inicios = marcar_suspeitos([inicio(1, 300), inicio(3, 1200)])
        self.assertEqual([i.numero for i in inicios if i.numero_suspeito], [])


if __name__ == "__main__":
    unittest.main()
