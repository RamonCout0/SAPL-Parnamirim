"""Tirar da fila uma faixa que ja foi cadastrada A MAO, no meio do acervo.

O caso real que originou isto: a faixa 1901-1945 de 2023 foi cadastrada no
SAPL por fora do programa, e hoje o trabalho esta no lote 1000-901. O unico
jeito de tirar algo da fila era "Já enviei até aqui", que so sabe remover um
pedaco INICIAL - e nao existe numero que alcance a 1901-1945 sem levar junto
centenas que ainda faltam enviar. Sem faixa, a alternativa era conviver com
indicacoes ja cadastradas dentro da fila, e uma fila assim nao pode ser usada
no "todas" do envio automatico: cada uma delas viraria materia em dobro.

O que se testa aqui nao e "a funcao fatia direito". E:

  - a faixa pega EXATAMENTE o que foi pedido, nos dois sentidos de lote, sem
    encostar em quem esta antes ou depois;
  - escrever os numeros na ordem contraria a do PDF nao devolve vazio (nem,
    pior, uma faixa diferente);
  - o que sai da fila fica gravado como "declarado" e nao como "automatico",
    porque ninguem viu o cadastro acontecer;
  - devolver para a fila alcanca o declarado e NUNCA o que o programa cadastrou
    e conferiu na tela do SAPL.

    .venv\\Scripts\\python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.enviados import (AUTOMATICO, DECLARADO, esquecer, ler_enviados,
                          marcar_varias)
from src.sapl import entre_numeros


def fila(numeros, ano=2023):
    return [{"numero": n, "ano": ano} for n in numeros]


class TestFaixaEntreNumeros(unittest.TestCase):
    # O lote de verdade: o PDF 2030_A_1901 vem de tras para frente.
    DESCENDO = fila(range(2030, 1900, -1))
    SUBINDO = fila(range(601, 711), ano=2022)

    def test_faixa_no_meio_do_lote_nao_leva_os_vizinhos(self):
        """O caso que nao existia: 1901-1945 fica no MEIO da fila de 2030 a
        1901. Tirar essas nao pode encostar nas 2030-1946."""
        faixa = entre_numeros(self.DESCENDO, 1945, 1901)
        self.assertEqual(len(faixa), 45)
        self.assertEqual(faixa[0]["numero"], 1945)
        self.assertEqual(faixa[-1]["numero"], 1901)
        # o que fica de fora continua inteiro
        restante = [i for i in self.DESCENDO if i not in faixa]
        self.assertEqual(len(restante), len(self.DESCENDO) - 45)
        self.assertEqual(restante[-1]["numero"], 1946)

    def test_ordem_contraria_a_do_lote_nomeia_os_mesmos_documentos(self):
        """"da 1901 ate a 1945" e "da 1945 ate a 1901" sao a mesma faixa.

        Qual das duas casa com o sentido da lista depende do PDF, e ninguem
        tem obrigacao de saber isso de cor na hora de digitar. Devolver vazio
        aqui mandaria a pessoa procurar erro em numero que estava certo.
        """
        self.assertEqual(entre_numeros(self.DESCENDO, 1901, 1945),
                         entre_numeros(self.DESCENDO, 1945, 1901))

    def test_lote_crescente(self):
        faixa = entre_numeros(self.SUBINDO, 605, 610)
        self.assertEqual([i["numero"] for i in faixa],
                         [605, 606, 607, 608, 609, 610])

    def test_so_o_ate_repete_o_botao_antigo(self):
        """"Já enviei até aqui" nao sumiu: virou o caso de deixar o "de" em
        branco. Se isto quebrar, quem so usava o botao velho perde o caminho."""
        faixa = entre_numeros(self.SUBINDO, None, 605)
        self.assertEqual([i["numero"] for i in faixa], [601, 602, 603, 604, 605])

    def test_so_o_de_vai_ate_o_fim(self):
        faixa = entre_numeros(self.SUBINDO, 708, None)
        self.assertEqual([i["numero"] for i in faixa], [708, 709, 710])

    def test_uma_indicacao_so(self):
        """A avulsa: a 1476 cadastrada solta meses atras."""
        faixa = entre_numeros(self.DESCENDO, 1976, 1976)
        self.assertEqual(len(faixa), 1)
        self.assertEqual(faixa[0]["numero"], 1976)

    def test_faixa_fora_do_lote_devolve_vazio(self):
        """Vazio e o sinal de "nao achei", e a tela avisa. Devolver a fila
        inteira aqui marcaria centenas como enviadas por um numero errado."""
        self.assertEqual(entre_numeros(self.SUBINDO, 900, 950), [])

    def test_fila_embaralhada_nao_estica_a_faixa(self):
        """A fila NAO e um lote so - e o que sobrou de varios.

        O output/indicacoes.json de hoje desce de 1000 a 986 e termina numa
        2472 solta. Resolvendo a faixa por comparacao de numero, "de 995 ate
        1000" enxergava a lista como decrescente por causa da 2472 no fim e
        devolvia 10 indicacoes em vez de 6. As quatro a mais sairiam da fila
        marcadas como cadastradas sem nunca ter entrado no SAPL.
        """
        real = fila(range(1000, 985, -1)) + fila([2472])
        faixa = entre_numeros(real, 995, 1000)
        self.assertEqual([i["numero"] for i in faixa],
                         [1000, 999, 998, 997, 996, 995])
        self.assertEqual(entre_numeros(real, 1000, 995), faixa)

    def test_numero_que_ja_saiu_da_fila_cai_no_vizinho(self):
        """Depois de marcar, a fila fica com buracos. Digitar um numero que ja
        saiu nao pode falhar - a pessoa esta lendo o papel, nao a tela."""
        sem_1920 = [i for i in self.DESCENDO if i["numero"] != 1920]
        faixa = entre_numeros(sem_1920, 1920, 1918)
        self.assertEqual([i["numero"] for i in faixa], [1919, 1918])


class TestRegistroDaFaixa(unittest.TestCase):
    """O que a marcacao grava - e o que ela deixa desfazer."""

    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.arquivo = Path(self.pasta.name) / "enviados.json"

    def tearDown(self):
        self.pasta.cleanup()

    def test_faixa_marcada_sai_como_declarado(self):
        """"declarado" e "automatico" nao podem virar a mesma coisa: a faixa e
        a sua palavra de que cadastrou, nao um cadastro que o programa viu."""
        faixa = entre_numeros(fila(range(2030, 1900, -1)), 1945, 1901)
        ids = [f"{i['numero']}/{i['ano']}" for i in faixa]
        marcar_varias(ids, origem=DECLARADO, caminho=self.arquivo)

        guardado = ler_enviados(self.arquivo)
        self.assertEqual(len(guardado), 45)
        self.assertTrue(all(v["origem"] == DECLARADO for v in guardado.values()))

    def test_marcar_faixa_nao_rebaixa_o_que_o_programa_cadastrou(self):
        """Uma faixa larga por cima de uma indicacao ja cadastrada pelo
        programa nao pode apagar a testemunha do envio."""
        marcar_varias(["1910/2023"], url="https://sapl/materia/7",
                      origem=AUTOMATICO, caminho=self.arquivo)
        faixa = entre_numeros(fila(range(2030, 1900, -1)), 1945, 1901)
        marcar_varias([f"{i['numero']}/{i['ano']}" for i in faixa],
                      origem=DECLARADO, caminho=self.arquivo)

        registro = ler_enviados(self.arquivo)["1910/2023"]
        self.assertEqual(registro["origem"], AUTOMATICO)
        self.assertEqual(registro["url"], "https://sapl/materia/7")

    def test_devolver_para_a_fila_tira_do_registro(self):
        """O caminho de volta que faltava: o Desfazer so alcanca a ultima
        marcacao da sessao, e quem errasse e fechasse o programa ficava com uma
        indicacao marcada como cadastrada sem nunca ter entrado no SAPL."""
        marcar_varias(["1930/2023", "1931/2023"], origem=DECLARADO,
                      caminho=self.arquivo)
        self.assertEqual(esquecer(["1930/2023"], caminho=self.arquivo), 1)

        guardado = ler_enviados(self.arquivo)
        self.assertNotIn("1930/2023", guardado)
        self.assertIn("1931/2023", guardado)


if __name__ == "__main__":
    unittest.main(verbosity=2)
