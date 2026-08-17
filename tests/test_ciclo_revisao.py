"""Regressao do ciclo de revisao manual.

O bug que estes testes travam: a correcao digitada era perdida na rodada
seguinte do pipeline, porque o glossario.csv - regravado a cada rodada, e so
com as pendentes - era o unico lugar onde ela ficava guardada. Na pratica a
mesma indicacao voltava para revisao para sempre.

    .venv\\Scripts\\python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import pipeline, revisao
from src.pipeline import Indicacao, _aplicar_correcoes_manuais, _classificar
from src.revisao import (
    escrever_glossario,
    importar_do_glossario,
    ler_correcoes,
    ler_glossario,
    registrar_correcao,
)

IDS = {
    "autores": [
        {"id": 11, "nome": "Binho de Ambrósio", "parlamentar": True},
        {"id": 12, "nome": "Eder Queiroz", "parlamentar": True},
    ]
}


class TestIndicacaoSemAutor(unittest.TestCase):
    """A indicacao assinada por TODOS os vereadores.

    Caso real, 439/2023: o texto diz "Os Vereadores da Camara Municipal de
    Parnamirim/RN ... INDICAM" e as assinaturas ocupam tres paginas inteiras.
    Nao ha um autor individual para escolher, e a extracao nao acha nome
    nenhum - com razao, porque sao treze.

    A tentacao seria deixar de exigir autor. Nao da: aquela exigencia e o que
    segura a indicacao cuja assinatura o OCR nao leu. Entao "nao tem autor"
    passou a ser uma RESPOSTA sua, marcada na conferencia e gravada - e so ela
    libera o envio.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.correcoes = self.tmp / "correcoes.json"
        self.glossario = self.tmp / "glossario.csv"
        self._originais = (revisao.CORRECOES, pipeline.CORRECOES, pipeline.GLOSSARIO)
        revisao.CORRECOES = self.correcoes
        pipeline.CORRECOES = self.correcoes
        pipeline.GLOSSARIO = self.glossario

    def tearDown(self):
        revisao.CORRECOES, pipeline.CORRECOES, pipeline.GLOSSARIO = self._originais

    def _linha(self) -> dict:
        return {"numero": "439", "ano": "2023", "paginas": "134-139",
                "precisa": "data, ementa, autor", "NUMERO_MANUAL": "",
                "DATA_MANUAL": "", "EMENTA_MANUAL": "", "AUTOR_ID_MANUAL": "",
                "SEM_AUTOR": "", "CONFIRMAR": "", "motivo": ""}

    def test_autor_vazio_continua_faltando(self):
        """O caso comum: a maquina nao leu a assinatura. Tem de parar."""
        self.assertIn("autor", revisao.falta_em(self._linha()))

    def test_marcar_sem_autor_resolve_a_exigencia(self):
        linha = self._linha()
        linha["SEM_AUTOR"] = "sim"
        self.assertNotIn("autor", revisao.falta_em(linha))

    def test_sem_autor_e_gravado_no_correcoes(self):
        revisao.escrever_glossario([self._linha()], self.glossario)
        revisao.salvar_correcao(self.glossario, "439", "2023", paginas="134-139",
                                sem_autor=True, data="22/03/2023",
                                ementa="APOIO DAS FORCAS ARMADAS AO ESTADO.")
        guardado = revisao.ler_correcoes(self.correcoes)["439/2023"]
        self.assertTrue(guardado["sem_autor"])

    def test_escolher_vereador_desfaz_o_sem_autor(self):
        """Sao respostas opostas para a mesma pergunta: a ultima vale."""
        revisao.registrar_correcao("439/2023", sem_autor=True,
                                   caminho=self.correcoes)
        revisao.registrar_correcao("439/2023", autor_id=11,
                                   caminho=self.correcoes)
        guardado = revisao.ler_correcoes(self.correcoes)["439/2023"]
        self.assertEqual(guardado["autor_id"], 11)
        self.assertNotIn("sem_autor", guardado)

    def test_indicacao_marcada_fica_pronta(self):
        revisao.registrar_correcao(
            "439/2023", sem_autor=True, data="22/03/2023",
            ementa="APOIO DAS FORCAS ARMADAS PARA A SEGURANCA DO ESTADO DO RN.",
            caminho=self.correcoes)
        ind = indicacao(numero=439, ano=2023, numero_lido=439,
                        data_apresentacao="", confianca=1.0)

        _aplicar_correcoes_manuais([ind], IDS, ResolvedorFalso())
        _classificar(ind)

        self.assertTrue(ind.sem_autor)
        self.assertEqual(ind.status, "pronto", ind.motivos)

    def test_sem_a_marca_continua_em_revisao(self):
        """A mesma indicacao, sem a sua marca, NAO passa."""
        revisao.registrar_correcao(
            "439/2023", data="22/03/2023",
            ementa="APOIO DAS FORCAS ARMADAS PARA A SEGURANCA DO ESTADO DO RN.",
            caminho=self.correcoes)
        ind = indicacao(numero=439, ano=2023, numero_lido=439,
                        data_apresentacao="", confianca=1.0)

        _aplicar_correcoes_manuais([ind], IDS, ResolvedorFalso())
        _classificar(ind)

        self.assertEqual(ind.status, "revisao")
        self.assertIn("autor", ind.falta)


class ResolvedorFalso:
    """So o suficiente para _aplicar_correcoes_manuais: aprender aliases nao e
    o que estes testes verificam."""

    def aprender(self, *args, **kwargs) -> bool:
        return False


def indicacao(**kwargs) -> Indicacao:
    # data_apresentacao ja vem preenchida porque o SAPL nao aceita cadastro
    # sem ela - e agora e o programa que preenche o campo no formulario. Os
    # testes que verificam a exigencia da data passam data_apresentacao="".
    base = dict(
        numero=1405, ano=2022, pagina_inicial=1, pagina_final=2, qtd_paginas=2,
        data_apresentacao="16/12/2022",
    )
    base.update(kwargs)
    return Indicacao(**base)


class BaseTemp(unittest.TestCase):
    """Aponta os arquivos de trabalho para uma pasta temporaria."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.correcoes = self.tmp / "correcoes.json"
        self.glossario = self.tmp / "glossario.csv"

        self._originais = (revisao.CORRECOES, pipeline.CORRECOES, pipeline.GLOSSARIO)
        revisao.CORRECOES = self.correcoes
        pipeline.CORRECOES = self.correcoes
        pipeline.GLOSSARIO = self.glossario

    def tearDown(self):
        revisao.CORRECOES, pipeline.CORRECOES, pipeline.GLOSSARIO = self._originais


class TestMemoriaPermanente(BaseTemp):
    def test_registrar_e_ler(self):
        registrar_correcao("1405/2022", ementa="PAVIMENTAÇÃO DA RUA X", autor_id=11)
        guardado = ler_correcoes(self.correcoes)["1405/2022"]
        self.assertEqual(guardado["ementa"], "PAVIMENTAÇÃO DA RUA X")
        self.assertEqual(guardado["autor_id"], 11)

    def test_gravar_so_o_autor_nao_apaga_a_ementa(self):
        """O caso real: numa passagem voce transcreve a ementa, noutra escolhe
        o vereador. A segunda gravacao nao pode zerar a primeira."""
        registrar_correcao("1405/2022", ementa="PAVIMENTAÇÃO DA RUA X")
        registrar_correcao("1405/2022", autor_id=12)

        guardado = ler_correcoes(self.correcoes)["1405/2022"]
        self.assertEqual(guardado["ementa"], "PAVIMENTAÇÃO DA RUA X")
        self.assertEqual(guardado["autor_id"], 12)

    def test_importa_o_que_foi_digitado_na_planilha(self):
        escrever_glossario(
            [{
                "numero": "1405", "ano": "2022", "paginas": "1-2",
                "EMENTA_MANUAL": "TEXTO DIGITADO NO EXCEL",
                "AUTOR_ID_MANUAL": "11", "CONFIRMAR": "sim",
            }],
            self.glossario,
        )
        self.assertEqual(importar_do_glossario(self.glossario, self.correcoes), 1)

        guardado = ler_correcoes(self.correcoes)["1405/2022"]
        self.assertEqual(guardado["ementa"], "TEXTO DIGITADO NO EXCEL")
        self.assertEqual(guardado["autor_id"], 11)
        self.assertTrue(guardado["confirmado"])

    def test_importar_de_novo_sem_mudanca_nao_reescreve(self):
        escrever_glossario(
            [{"numero": "1405", "ano": "2022", "EMENTA_MANUAL": "X" * 50}],
            self.glossario,
        )
        importar_do_glossario(self.glossario, self.correcoes)
        self.assertEqual(importar_do_glossario(self.glossario, self.correcoes), 0)


class TestCorrecaoSobreviveAsRodadas(BaseTemp):
    """O coracao do bug: o que voce corrigiu tem de continuar valendo na
    proxima extracao, mesmo depois de a indicacao virar "pronto" e sair da
    lista de pendentes."""

    def _rodada(self, inds: list[Indicacao]) -> list[Indicacao]:
        """Uma passagem do pipeline sobre indicacoes recem-extraidas."""
        _aplicar_correcoes_manuais(inds, IDS, ResolvedorFalso())
        for ind in inds:
            _classificar(ind)
        return inds

    def test_ementa_corrigida_continua_valendo_na_rodada_seguinte(self):
        registrar_correcao(
            "1405/2022",
            ementa="INDICA A PAVIMENTAÇÃO DA RUA DAS FLORES, NO BAIRRO NOVA PARNAMIRIM",
            autor_id=11,
        )
        # Duas extracoes seguidas do mesmo PDF: a maquina le a mesma coisa
        # ruim das duas vezes, a correcao e que tem de mandar.
        for rodada in (1, 2):
            with self.subTest(rodada=rodada):
                ind = self._rodada([indicacao(ementa="", confianca=0.0)])[0]
                self.assertEqual(ind.status, "pronto", ind.motivos)
                self.assertEqual(ind.autor_id, 11)
                self.assertIn("PAVIMENTAÇÃO", ind.ementa)

    def test_confirmacao_resolve_numero_deduzido(self):
        """"numero deduzido" e "1 pagina" nao tem o que digitar - so o
        CONFIRMAR resolve. Como o CONFIRMAR morava no CSV apagado, essas duas
        eram pendencia eterna."""
        ementa_boa = "INDICA A PODA DAS ÁRVORES DA PRAÇA CENTRAL DO BAIRRO"
        antes = self._rodada([
            indicacao(ementa=ementa_boa, confianca=0.9, autor_id=11,
                      numero_inferido=True)
        ])[0]
        self.assertEqual(antes.status, "revisao")
        self.assertEqual(antes.falta, ["confirmar"])

        registrar_correcao("1405/2022", confirmado=True)
        depois = self._rodada([
            indicacao(ementa=ementa_boa, confianca=0.9, autor_id=11,
                      numero_inferido=True)
        ])[0]
        self.assertEqual(depois.status, "pronto", depois.motivos)

    def test_ementa_manual_curta_nao_e_barrada(self):
        """Ementa transcrita por uma pessoa nao passa pelo criterio de
        tamanho: o criterio existe para desconfiar do OCR, e aqui nao ha OCR."""
        registrar_correcao("1405/2022", ementa="INDICA A PODA DE ÁRVORE", autor_id=11)
        ind = self._rodada([indicacao(ementa="", confianca=0.0)])[0]
        self.assertEqual(ind.status, "pronto", ind.motivos)

    def test_autor_invalido_vira_aviso(self):
        registrar_correcao("1405/2022", ementa="X" * 60)
        correcoes = ler_correcoes(self.correcoes)
        correcoes["1405/2022"]["autor_id_invalido"] = "Binho"
        revisao.gravar_correcoes(correcoes, self.correcoes)

        ind = self._rodada([indicacao(ementa="", confianca=0.0)])[0]
        self.assertEqual(ind.status, "revisao")
        self.assertTrue(any("nao e numero" in m for m in ind.motivos), ind.motivos)


class TestDataObrigatoria(BaseTemp):
    """Sem data nao da para cadastrar: e o programa que preenche o campo no
    SAPL, e a data tambem e o que destrava o select de autor (o SAPL filtra
    pelo mandato vigente naquela data). Como ela e escrita a mao no carimbo do
    verso, sempre vem de voce."""

    def test_sem_data_nao_vai_sozinha(self):
        ind = indicacao(data_apresentacao="", ementa="X" * 60, confianca=0.9,
                        autor_id=11)
        _classificar(ind)
        self.assertEqual(ind.status, "revisao")
        self.assertEqual(ind.falta, ["data"])

    def test_data_digitada_resolve(self):
        registrar_correcao("1405/2022", data="13/12/2022")
        ind = indicacao(data_apresentacao="", ementa="X" * 60, confianca=0.9,
                        autor_id=11)
        _aplicar_correcoes_manuais([ind], IDS, ResolvedorFalso())
        _classificar(ind)
        self.assertEqual(ind.status, "pronto", ind.motivos)
        self.assertEqual(ind.data_apresentacao, "13/12/2022")
        self.assertEqual(ind.data_origem, "manual")

    def test_data_digitada_sobrevive_a_rodada_seguinte(self):
        registrar_correcao("1405/2022", data="13/12/2022")
        for rodada in (1, 2, 3):
            with self.subTest(rodada=rodada):
                ind = indicacao(data_apresentacao="", ementa="X" * 60,
                                confianca=0.9, autor_id=11)
                _aplicar_correcoes_manuais([ind], IDS, ResolvedorFalso())
                _classificar(ind)
                self.assertEqual(ind.data_apresentacao, "13/12/2022")


class TestOQueFalta(BaseTemp):
    """A coluna "precisa": quais dos tres campos resolvem cada indicacao."""

    def test_falta_ementa_e_autor(self):
        ind = indicacao(ementa="", confianca=0.0)
        _classificar(ind)
        self.assertEqual(ind.falta, ["ementa", "autor"])

    def test_falta_so_o_autor(self):
        ind = indicacao(ementa="INDICA A PAVIMENTAÇÃO DA RUA DAS FLORES NO BAIRRO",
                        confianca=0.9)
        _classificar(ind)
        self.assertEqual(ind.falta, ["autor"])

    def test_indicacao_completa_nao_pede_nada(self):
        ind = indicacao(ementa="INDICA A PAVIMENTAÇÃO DA RUA DAS FLORES NO BAIRRO",
                        confianca=0.9, autor_id=11)
        _classificar(ind)
        self.assertEqual(ind.falta, [])
        self.assertEqual(ind.status, "pronto")


class TestRegravacaoDoGlossario(BaseTemp):
    """_preparar_revisao regrava o glossario.csv a cada rodada. Era AQUI que o
    trabalho do usuario era destruido: as colunas manuais voltavam em branco."""

    def setUp(self):
        super().setUp()
        pipeline.REVISAO_DIR = self.tmp
        # Renderizar PNG exige o PDF de verdade; o que este teste verifica e o
        # CSV, entao a exportacao vira um stub.
        self._png = pipeline.exportar_paginas_png
        pipeline.exportar_paginas_png = lambda *a, **k: ["1405-2022_pg001.png"]

    def tearDown(self):
        pipeline.exportar_paginas_png = self._png
        super().tearDown()

    def test_colunas_manuais_voltam_preenchidas(self):
        registrar_correcao("1405/2022", ementa="EMENTA QUE EU TRANSCREVI DO PAPEL")

        # Continua pendente: falta o autor. A ementa ja digitada NAO pode
        # sumir do arquivo por causa disso.
        ind = indicacao(ementa="", confianca=0.0, arquivo_origem="lote.pdf")
        _aplicar_correcoes_manuais([ind], IDS, ResolvedorFalso())
        _classificar(ind)
        pipeline._preparar_revisao([ind], IDS)

        linha = list(ler_glossario(self.glossario).values())
        self.assertTrue(linha, "a pendente tem de continuar no glossario")

        import csv as _csv

        with open(self.glossario, encoding="utf-8-sig", newline="") as f:
            bruta = next(_csv.DictReader(f, delimiter=";"))
        self.assertEqual(bruta["EMENTA_MANUAL"], "EMENTA QUE EU TRANSCREVI DO PAPEL")
        self.assertEqual(bruta["precisa"], "autor")

    def test_glossario_editado_a_mao_e_importado_antes_de_ser_regravado(self):
        """O caminho "avancado" do README: editar a planilha direto. O texto
        digitado tem de chegar ao correcoes.json antes de qualquer regravacao."""
        escrever_glossario(
            [{
                "numero": "1405", "ano": "2022", "paginas": "1-2",
                "EMENTA_MANUAL": "DIGITEI ISTO NO EXCEL", "AUTOR_ID_MANUAL": "11",
            }],
            self.glossario,
        )

        ind = indicacao(ementa="", confianca=0.0, arquivo_origem="lote.pdf")
        _aplicar_correcoes_manuais([ind], IDS, ResolvedorFalso())
        _classificar(ind)

        self.assertEqual(ind.status, "pronto", ind.motivos)
        self.assertEqual(ind.ementa, "DIGITEI ISTO NO EXCEL")
        self.assertEqual(ler_correcoes(self.correcoes)["1405/2022"]["autor_id"], 11)

        # Resolvida: sai do glossario - mas o correcoes.json continua com ela,
        # que e o que impede de voltar para revisao na proxima rodada.
        pipeline._preparar_revisao([ind], IDS)
        self.assertEqual(ler_glossario(self.glossario), {})
        self.assertIn("1405/2022", ler_correcoes(self.correcoes))


class TestFilaDaTelaDeRevisao(unittest.TestCase):
    """A tela considerava resolvida a linha em que UM dos tres campos estivesse
    preenchido - por isso "pulava" indicacoes ainda defeituosas."""

    @staticmethod
    def _falta(linha: dict) -> list[str]:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import importlib.util

        caminho = Path(__file__).resolve().parent.parent / "scripts" / "03_revisar.py"
        spec = importlib.util.spec_from_file_location("revisar", caminho)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        return modulo.falta_em(linha)

    def test_meia_correcao_nao_conta_como_resolvida(self):
        linha = {
            "precisa": "ementa, autor",
            "EMENTA_MANUAL": "JÁ TRANSCREVI A EMENTA",
            "AUTOR_ID_MANUAL": "",
            "CONFIRMAR": "",
        }
        self.assertEqual(self._falta(linha), ["autor"])

    def test_correcao_completa_sai_da_fila(self):
        linha = {
            "precisa": "ementa, autor",
            "EMENTA_MANUAL": "JÁ TRANSCREVI A EMENTA",
            "AUTOR_ID_MANUAL": "11",
            "CONFIRMAR": "",
        }
        self.assertEqual(self._falta(linha), [])

    def test_glossario_antigo_sem_a_coluna_precisa(self):
        # Arquivo gerado pela versao anterior: deduz pelo texto do motivo.
        linha = {
            "motivo": "ementa vazia | autor nao identificado",
            "EMENTA_MANUAL": "TEXTO",
            "AUTOR_ID_MANUAL": "",
            "CONFIRMAR": "",
        }
        self.assertEqual(self._falta(linha), ["autor"])


class TestLerGlossario(unittest.TestCase):
    def test_linha_em_branco_e_ignorada(self):
        with tempfile.TemporaryDirectory() as d:
            caminho = Path(d) / "g.csv"
            escrever_glossario(
                [
                    {"numero": "1405", "ano": "2022", "EMENTA_MANUAL": "TEXTO"},
                    {"numero": "1404", "ano": "2022"},
                ],
                caminho,
            )
            lido = ler_glossario(caminho)
            self.assertIn("1405/2022", lido)
            self.assertNotIn("1404/2022", lido)


if __name__ == "__main__":
    unittest.main()
