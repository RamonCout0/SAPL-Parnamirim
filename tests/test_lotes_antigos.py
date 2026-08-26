"""Regressao das correcoes achadas no teste dos lotes de 2009 a 2020.

Roda sem nenhuma dependencia externa (nao fala com o SAPL nem com o Ollama):

    .venv\\Scripts\\python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.autores import ResolvedorAutor
from src.campos import extrair_ementa, problemas_na_ementa
from src.pipeline import Indicacao, _ano_do_nome_arquivo, _classificar


class AnoNoNomeDoArquivo(unittest.TestCase):
    """O "@AAAA" pode estar em qualquer posicao, nao so no fim.

    A versao anterior exigia que o nome TERMINASSE em "@AAAA.pdf" e falhava em
    silencio em todo lote dividido em partes - 46 dos 78 PDFs reais de
    2009-2020. Sem aviso nenhum, eles caiam no ano padrao.
    """

    def test_no_fim_continua_valendo(self):
        self.assertEqual(_ano_do_nome_arquivo(Path("TODAS@2009.pdf")), 2009)
        self.assertEqual(_ano_do_nome_arquivo(Path("TODAS_P10@2018.pdf")), 2018)

    def test_com_sufixo_de_parte(self):
        casos = {
            "TODAS_INDICACOES@2010.p1.pdf": 2010,
            "TODAS_INDICACOES@2013.P1.pdf": 2013,
            "TODAS_INDICACOES@2016.P1-1.pdf": 2016,
            "TODAS_ATUALIZADAS@2019_P10_frenteverso.pdf": 2019,
        }
        for nome, esperado in casos.items():
            with self.subTest(nome=nome):
                self.assertEqual(_ano_do_nome_arquivo(Path(nome)), esperado)

    def test_sem_ano_no_nome(self):
        self.assertIsNone(_ano_do_nome_arquivo(Path("lote_qualquer.pdf")))

    def test_numero_que_nao_e_ano(self):
        """"@9999" e protocolo, nao ano: melhor devolver None e deixar o
        --ano decidir do que cadastrar o lote num ano inventado."""
        self.assertIsNone(_ano_do_nome_arquivo(Path("lote@9999.pdf")))

    def test_mais_de_um_arroba_vence_o_ultimo(self):
        self.assertEqual(_ano_do_nome_arquivo(Path("x@2011_y@2015.pdf")), 2015)


# Texto real da indicacao 24/2010, com o modelo antigo de papel.
PAPEL_ANTIGO_SUGERINDO = (
    "INDICAÇÃO N°24/2010\n"
    "Autora): Vereadora WALKIRIA FONSECA\n"
    "Senhor Presidente, Apresento a V.Exa., nos termos do Art° 148 do\n"
    "Regimento Interno, a presente Indicação, sugerindo ao Senhor Prefeito\n"
    "Providencias com relação a Reabertura do Posto Policial dos Conjuntos\n"
    "Jardins das Nações por se tratar de medida de interesse público.\n"
    "JUSTIFICAÇÃO\n"
    "A Presente Indicação se justifica diante das condições que se encontra.\n"
)

# Texto real da indicacao 45/2010: o verbo e o particípio "INDICADO".
PAPEL_ANTIGO_INDICADO = (
    "Indicação N°45/2010\n"
    "Senhor Presidente\n"
    "Elienai Dantas Cartaxo, vereadora com assento nesta Casa Legislativa,\n"
    "vem, nos termos regimentais, solicitar à Presidência da Mesa Diretora,\n"
    "que seja INDICADO ao Chefe do Executivo Municipal, o Sr. Maurício\n"
    "Marques, reparos na cobertura da parada de ônibus da Avenida Márcio\n"
    "Marinho, no Bairro de Pirangi do Norte.\n"
    "Justificativa\n"
    "O Pleito se justifica, visto que a cobertura encontra-se danificada.\n"
)

PAPEL_ATUAL = (
    "Senhor Presidente,\n"
    "Fulano de Tal, vereador com assento nesta egrégia Casa Legislativa,\n"
    "INDICA ao Excelentíssimo Senhor Prefeito a pavimentação da Rua das\n"
    "Flores, no bairro Nova Parnamirim, atendendo a pedido dos moradores.\n"
    "Justificativa\n"
    "O pleito se justifica pela poeira.\n"
)


class VerboDoPapelAntigo(unittest.TestCase):
    """"sugerindo" e "INDICADO" nao estavam em lista nenhuma: 160 das 426
    indicacoes de 2010 saiam com ementa vazia, acusando "verbo ilegivel no
    OCR" com o OCR perfeito."""

    def test_sugerindo(self):
        r = extrair_ementa(PAPEL_ANTIGO_SUGERINDO)
        self.assertTrue(r["ementa"], "ementa saiu vazia")
        self.assertEqual(r["verbo"], "SUGERINDO")
        self.assertTrue(r["ementa"].startswith("ao Senhor Prefeito"))
        self.assertNotIn("JUSTIFICAÇÃO", r["ementa"])
        self.assertNotIn("se justifica", r["ementa"])

    def test_indicado_participio(self):
        r = extrair_ementa(PAPEL_ANTIGO_INDICADO)
        self.assertTrue(r["ementa"], "ementa saiu vazia")
        self.assertEqual(r["verbo"], "INDICADO")
        self.assertIn("reparos na cobertura", r["ementa"])
        self.assertNotIn("se justifica", r["ementa"])

    def test_justificacao_encerra_a_ementa(self):
        """O papel antigo escreve JUSTIFICAÇÃO onde o atual escreve
        JUSTIFICATIVA. Sem as duas grafias a ementa engolia a justificativa."""
        r = extrair_ementa(PAPEL_ANTIGO_SUGERINDO)
        self.assertEqual(r["metodo"], "verbo-antigo..justificativa")

    def test_papel_atual_nao_muda(self):
        """A lista antiga so e consultada quando nenhum verbo atual casa."""
        r = extrair_ementa(PAPEL_ATUAL)
        self.assertEqual(r["verbo"], "INDICA")
        self.assertTrue(r["metodo"].startswith("verbo.."))
        self.assertIn("pavimentação da Rua das Flores", r["ementa"])

    def test_verbo_antigo_depois_da_justificativa_nao_vale(self):
        """Trava: "solicita"/"sugere" sao palavras comuns e aparecem no meio da
        justificacao. Se o verbo de verdade foi destruido pelo OCR, pescar um
        deles la embaixo produziria ementa tirada da justificativa - com
        confianca alta e nada denunciando."""
        texto = (
            "Indicação N°42/2010\n"
            "Sérgio Roberto, vereador, 1N,RICA a Excelentíssima Governadora\n"
            "a implantação de uma Central do Cidadão.\n"
            "JUSTIFICATIVA\n"
            "Em atendimento a população, solicitamos e sugerimos a implantação\n"
            "do referido pedido, pois trata-se de um apelo da comunidade.\n"
        )
        r = extrair_ementa(texto)
        self.assertEqual(r["metodo"], "sem-verbo")
        self.assertEqual(r["ementa"], "")


def _catalogo(autores: list[dict]) -> dict:
    return {"autores": autores}


class AliasDeUmaPalavra(unittest.TestCase):
    """ACIDENTE REAL (lote de 2009): a indicacao 459 foi para "Chicao" com
    escore 100 e certeza alta. A assinatura era "Francisco Gildasio de
    Figueiredo" - outra pessoa. Chicao tem o alias "Francisco", e
    token_set_ratio devolve 100 quando os tokens da chave sao subconjunto dos
    da consulta."""

    def setUp(self):
        self.ids = _catalogo([
            {"id": 22, "nome": "Chicão", "parlamentar": True,
             "aliases": ["Chicao", "Francisco"]},
            {"id": 34, "nome": "Serginho Muniz", "parlamentar": True,
             "aliases": ["Sérgio Muniz", "Serginho"]},
            {"id": 99, "nome": "Gildásio", "parlamentar": True,
             "aliases": ["Francisco Gildásio de Figueiredo"]},
            {"id": 16, "nome": "Binho de Ambrósio", "parlamentar": True,
             "aliases": ["Binho", "Hamilton Rademacker Pereira"]},
        ])

    def _resolvedor(self):
        r = ResolvedorAutor(self.ids, usar_ollama=False)
        r.cache = {}
        return r

    def test_nome_completo_ganha_do_alias_curto(self):
        r = self._resolvedor()
        self.assertEqual(r.resolver("Francisco Gildásio de Figueiredo")["id"], 99)

    def test_primeiro_nome_comum_nao_decide(self):
        """Alguem de fora do catalogo cujo nome contem "Francisco" nao pode
        virar Chicao so por isso."""
        r = self._resolvedor()
        res = r.resolver("Francisco Silva Neto")
        self.assertEqual(res["id"], 0)
        self.assertIn("francisco", res["motivo"])

    def test_apelido_proprio_continua_valendo(self):
        """"Binho" e de uma pessoa so - o teste de unicidade passa e ele
        continua resolvendo sozinho."""
        r = self._resolvedor()
        self.assertEqual(r.resolver("Binho")["id"], 16)

    def test_nome_civil_conhecido_continua_valendo(self):
        r = self._resolvedor()
        self.assertEqual(r.resolver("Hamilton Rademacker Pereira")["id"], 16)


class VereadorSemCadastroDeAutor(unittest.TestCase):
    """"Parlamentar" e "Autor" sao tabelas diferentes no SAPL. Sem registro de
    Autor o vereador nao aparece no select, com data nenhuma - o programa tem
    de dizer isso, e nao apontar um homonimo."""

    def setUp(self):
        self.ids = _catalogo([
            {"id": 10, "nome": "Carol Pires", "parlamentar": True,
             "aliases": ["Ana Carolina Carvalho de Lima Pires"]},
            {"id": 0, "nome": "Katia Pires", "parlamentar": True,
             "sem_cadastro_no_sapl": True,
             "legislaturas": ["13a (2009-2012)"],
             "aliases": ["Katia Carvalho de Lima"]},
        ])

    def test_reconhece_e_explica(self):
        r = ResolvedorAutor(self.ids, usar_ollama=False)
        r.cache = {}
        res = r.resolver("Katia Carvalho de Lima")
        self.assertEqual(res["id"], 0)
        self.assertIn("Katia Pires", res["motivo"])
        self.assertIn("nao tem cadastro de Autor no SAPL", res["motivo"])
        self.assertIn("13a (2009-2012)", res["motivo"])

    def test_nao_e_oferecido_como_candidato(self):
        """Escolher esse nome no glossario gravaria autor_id 0, que e
        justamente "nao resolvido"."""
        r = ResolvedorAutor(self.ids, usar_ollama=False)
        nomes = [c["nome"] for c in r.candidatos_proximos("Katia Carvalho de Lima", "")]
        self.assertNotIn("Katia Pires", nomes)

    def test_id_zero_nao_colide_no_por_id(self):
        r = ResolvedorAutor(self.ids, usar_ollama=False)
        self.assertNotIn(0, r.por_id)
        self.assertIn(10, r.por_id)


class AvisosDeOcrNaEmenta(unittest.TestCase):
    """Ementa que saiu com o tamanho e a estrutura certos ainda pode ter
    "INbICACÁO" no meio. Estes avisos apontam o trecho suspeito para a
    conferencia ir direto ao ponto.

    O outro lado importa tanto quanto: regra que grita a toa faz o usuario
    parar de ler aviso. Cada teste de "nao avisa" abaixo veio de texto REAL
    dos lotes de 2009-2020 que uma versao ingenua da regra marcava errado.
    """

    # --- o que TEM de avisar ---

    def test_caractere_impossivel_em_portugues(self):
        avisos = problemas_na_ementa("a instalação de refletores na Rua ì Senador")
        self.assertEqual(len(avisos), 1)
        self.assertIn("caractere que nao existe em portugues", avisos[0])
        self.assertIn("ì", avisos[0])

    def test_digito_no_meio_de_palavra(self):
        avisos = problemas_na_ementa("a implantação de sem4foro no cruzamento da rua")
        self.assertTrue(any("digito no meio de palavra" in a for a in avisos))

    def test_maiuscula_e_minuscula_misturadas(self):
        avisos = problemas_na_ementa("a presente INbICACAO ao senhor prefeito da cidade")
        self.assertTrue(any("maiuscula e minuscula misturadas" in a for a in avisos))

    def test_palavra_sem_vogal(self):
        avisos = problemas_na_ementa("a construção nncfnc da praça no bairro novo")
        self.assertTrue(any("palavra sem vogal" in a for a in avisos))

    def test_aponta_o_trecho_suspeito(self):
        """O aviso serve para saber ONDE olhar - sem o exemplo ele nao ajuda.

        "GUga1" e token real da 472/2009. Repare que "Guga1", com UMA maiuscula
        so e o digito no fim, e escrita normal e nao pode ser marcado - por
        isso a regra pede DUAS maiusculas antes da minuscula."""
        avisos = problemas_na_ementa("reforma da Rua GUga1 no bairro de Pirangi")
        self.assertTrue(any("GUga1" in a for a in avisos))
        self.assertEqual(
            problemas_na_ementa("reforma da Rua Guga1 no bairro de Pirangi"), []
        )

    def test_varios_problemas_viram_varios_avisos(self):
        avisos = problemas_na_ementa("a obra ~ na rua sem4foro com INbICACAO no meio")
        self.assertGreaterEqual(len(avisos), 3)

    # --- o que NAO pode avisar (texto real dos lotes) ---

    def test_aspas_e_travessao_sao_pontuacao(self):
        """2.224 aspas e 1.673 travessoes nas 7.840 ementas reais."""
        texto = ('a reforma da praça "Vinte e Um de Abril" — Nova Parnamirim, '
                 "por se tratar de medida de interesse público.")
        self.assertEqual(problemas_na_ementa(texto), [])

    def test_potencia_de_lampada_nao_e_erro(self):
        """"150w" e "70wts" aparecem as dezenas: e a potencia da lampada."""
        self.assertEqual(
            problemas_na_ementa("a troca das lâmpadas de 70w por 150w na avenida"), []
        )

    def test_sigla_de_orgao_sem_vogal_nao_e_erro(self):
        """SMTT, CBMRN e PMRN sao orgaos de verdade."""
        self.assertEqual(
            problemas_na_ementa("oficio à SMTT e ao CBMRN sobre o cruzamento"), []
        )

    def test_plural_de_sigla_nao_e_erro(self):
        """UBSs, ACDs, EPIs, PROFa - escrita normal, nao OCR quebrado."""
        for texto in ("a reforma das UBSs do município de Parnamirim",
                      "a compra de EPIs para os ACDs da rede municipal"):
            with self.subTest(texto=texto):
                self.assertEqual(problemas_na_ementa(texto), [])

    def test_codigo_de_rota_nao_e_erro(self):
        """"M68" e "R83" sao codigos; o digito esta no fim, nao no meio."""
        self.assertEqual(
            problemas_na_ementa("a sinalização da rota M68 até o bairro"), []
        )

    def test_portugues_com_muitas_palavras_curtas_nao_e_erro(self):
        """A regra de "texto picado" foi descartada por causa deste caso: 67%
        dos tokens tem 1-2 letras e o texto esta perfeito."""
        texto = ("os indicativos N° 061/2010 e N° 103/2011 junto à Presidência "
                 "da Casa, no que se refere a obra da rua")
        self.assertEqual(problemas_na_ementa(texto), [])

    def test_ementa_vazia_nao_gera_aviso(self):
        """Ementa vazia ja tem o motivo dela; nao precisa de outro em cima."""
        self.assertEqual(problemas_na_ementa(""), [])
        self.assertEqual(problemas_na_ementa("   "), [])

    def test_prefixo_ementa_para_a_tela_de_revisao(self):
        """O prefixo "ementa:" e o que faz _o_que_resolve mandar o aviso para o
        campo de ementa - e o que faz o aviso sumir quando voce transcreve."""
        for aviso in problemas_na_ementa("obra ~ na rua sem4foro"):
            self.assertTrue(aviso.startswith("ementa:"), aviso)


class EmentaSujaNaoVaiSozinhaParaOSapl(unittest.TestCase):
    """A trava que importa: ementa com marca de OCR quebrado nao pode virar
    registro oficial pelo envio automatico.

    O caminho tem tres portas, e este teste cuida da primeira, que e a que
    fecha as outras duas:
      1. _classificar poe o aviso em motivos -> status vira "revisao";
      2. gui/tela_sapl.py so carrega na fila quem esta "pronto";
      3. src/sapl.py confere status != "pronto" de novo antes de salvar.
    """

    def _indicacao_perfeita(self, ementa: str) -> Indicacao:
        """Tudo em ordem, de proposito: assim o unico motivo possivel de
        reprovacao e a ementa - que e o que este teste mede."""
        return Indicacao(
            numero=101, ano=2020, pagina_inicial=1, pagina_final=2,
            qtd_paginas=2, numero_lido=101,
            autor_id=16, autor_nome_sapl="Binho de Ambrósio",
            ementa=ementa,
            data_apresentacao="04/02/2020",
            ementa_metodo="verbo..justificativa", confianca=0.9,
        )

    LIMPA = ("ao Chefe do Executivo Municipal a pavimentação da Rua das "
             "Flores, no bairro de Nova Parnamirim, por se tratar de medida "
             "de interesse público")

    def test_a_perfeita_passa(self):
        """Se esta nao passar, o teste seguinte nao prova nada."""
        ind = self._indicacao_perfeita(self.LIMPA)
        _classificar(ind)
        self.assertEqual(ind.status, "pronto", ind.motivos)

    def test_ementa_com_lixo_de_ocr_e_barrada(self):
        ind = self._indicacao_perfeita(
            self.LIMPA.replace("Municipal", "Municipai INbICACAO")
        )
        _classificar(ind)
        self.assertEqual(ind.status, "revisao")
        self.assertIn("ementa", ind.falta)

    def test_caractere_estranho_barra(self):
        ind = self._indicacao_perfeita(self.LIMPA + " ~•")
        _classificar(ind)
        self.assertEqual(ind.status, "revisao")

    def test_ementa_transcrita_por_voce_nao_e_auditada(self):
        """Ementa manual nao tem OCR para desconfiar. Se ela fosse auditada,
        um travessao ou uma sigla legitima que voce digitou poderia prender a
        indicacao para sempre, sem campo nenhum que resolvesse."""
        ind = self._indicacao_perfeita(self.LIMPA + " ~•")
        ind.ementa_metodo = "manual"
        ind.confianca = 1.0
        _classificar(ind)
        self.assertEqual(ind.status, "pronto", ind.motivos)


if __name__ == "__main__":
    unittest.main()
