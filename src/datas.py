"""A data de apresentacao: onde ela esta, e por que a maquina nao le.

A data NAO e do lote: cada indicacao tem a sua. Elas chegam juntas num PDF so
porque foram digitalizadas juntas - num lote real ha 48 datas diferentes entre
196 indicacoes.

A data que vale para o SAPL e a do carimbo "Lido na Sessão", no VERSO (quase
sempre a segunda pagina do bloco) - nao a do fecho da indicacao ("Plenário
Dr. Mário Medeiros, 16 de dezembro de 2021"), que e quando o vereador
assinou.

E ela e ESCRITA A MAO no carimbo. Medido nos dois lotes de 2021: dos 117
carimbos encontrados, o OCR entregou uma data legivel em ZERO. E assim que
eles saem do scanner:

    Mesa Diretora | Lido na Sessa© | Data: U ! t 3-
    Mesa Dia etora | Lido na Sessao | Data: l t / c j
    Mesa [3iret7ra | Lido na Sessão | • Data: 105 i~oad

Por isso este modulo NAO promete adivinhar a data. O que ele faz e ACHAR A
PAGINA do carimbo, para a interface mostrar justamente essa imagem na hora em
que voce vai digitar - voce le a letra de mao na tela e escreve, uma vez so.
A leitura automatica continua tentando (se algum dia o carimbo vier
datilografado, ela pega), mas nunca a partir da data do Plenario: oferecer a
data errada para copiar e pior do que nao oferecer nenhuma.

O mes por extenso, quando aparece, vem destrocado pelo OCR ("dehembro",
"Dezeinbro", "dezernbro"), entao e resolvido por semelhanca (rapidfuzz) - o
mesmo mecanismo ja usado para casar nome de vereador.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz, process

MESES = [
    "janeiro", "fevereiro", "marco", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]

# Abaixo disso a palavra nao e mes nenhum - e outra palavra qualquer entre
# dois numeros. Medido nos casos reais: "dehembro" da 88, "Dezeinbro" 84,
# "dezernbro" 84; uma palavra que nao e mes fica bem abaixo de 70.
SEMELHANCA_MINIMA = 72

# "16 de dezembro de 2021" - o "de" tambem sai errado do OCR ("dc", "cle"),
# entao a ligacao entre as partes e frouxa de proposito.
_POR_EXTENSO = re.compile(
    r"(\d{1,2})\s*[a-zç]{0,3}\s+([a-zà-ÿ]{3,12})\s*[a-zç]{0,3}\s+(\d{4})",
    re.IGNORECASE,
)
_NUMERICA = re.compile(r"\b(\d{1,2})\s*[/.]\s*(\d{1,2})\s*[/.]\s*(\d{4})\b")

# Onde a data aparece. A ordem e a de confianca: o fecho da indicacao vence o
# carimbo do verso, que vence o protocolo.
_ORIGENS = [
    ("plenario", re.compile(r"plen[aá]?r?[ií]?o|sala\s+das\s+sess", re.IGNORECASE)),
    ("lido em sessao", re.compile(r"lido\s+na\s+sess", re.IGNORECASE)),
    ("protocolo", re.compile(r"recebido|protocolo", re.IGNORECASE)),
]

# Quanto texto antes da data conta para saber de onde ela veio.
_JANELA_ORIGEM = 60


@dataclass
class DataAchada:
    dia: int
    mes: int
    ano: int
    origem: str
    trecho: str

    @property
    def formatada(self) -> str:
        return f"{self.dia:02d}/{self.mes:02d}/{self.ano}"

    @property
    def confianca(self) -> float:
        """O fecho da indicacao e a data de apresentacao de verdade; as outras
        sao aproximacoes uteis, mas para conferir."""
        return {"plenario": 0.9, "lido em sessao": 0.6, "protocolo": 0.5}.get(
            self.origem, 0.4)


def _mes_por_semelhanca(palavra: str) -> int | None:
    achado = process.extractOne(
        palavra.lower(), MESES, scorer=fuzz.ratio, score_cutoff=SEMELHANCA_MINIMA
    )
    return MESES.index(achado[0]) + 1 if achado else None


def _origem(texto: str, posicao: int) -> str:
    """De onde veio esta data: vale a marca MAIS PROXIMA dela.

    Nao a de maior prioridade: num verso com "Lido na Sessão do dia 20 ...
    RECEBIDO em 21 ...", as duas marcas cabem na janela da segunda data, e
    escolher pela prioridade daria "lido em sessao" para a data do protocolo.
    """
    antes = texto[max(0, posicao - _JANELA_ORIGEM):posicao]
    melhor, mais_perto = "solta no texto", -1
    for nome, regex in _ORIGENS:
        for m in regex.finditer(antes):
            if m.start() > mais_perto:
                mais_perto, melhor = m.start(), nome
    return melhor


def _plausivel(dia: int, mes: int, ano: int) -> bool:
    # Ano de indicacao municipal: nem 1900, nem 2100. Fora disso e ruido de
    # OCR que por acaso formou tres numeros.
    return 1 <= dia <= 31 and 1 <= mes <= 12 and 1990 <= ano <= 2100


def achar_datas(texto: str) -> list[DataAchada]:
    """Todas as datas do texto, da mais confiavel para a menos."""
    achadas: list[DataAchada] = []

    for m in _POR_EXTENSO.finditer(texto):
        mes = _mes_por_semelhanca(m.group(2))
        if mes is None:
            continue
        dia, ano = int(m.group(1)), int(m.group(3))
        if not _plausivel(dia, mes, ano):
            continue
        achadas.append(DataAchada(
            dia, mes, ano, _origem(texto, m.start()),
            texto[max(0, m.start() - 40):m.end()].replace("\n", " ").strip(),
        ))

    for m in _NUMERICA.finditer(texto):
        dia, mes, ano = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not _plausivel(dia, mes, ano):
            continue
        achadas.append(DataAchada(
            dia, mes, ano, _origem(texto, m.start()),
            texto[max(0, m.start() - 40):m.end()].replace("\n", " ").strip(),
        ))

    achadas.sort(key=lambda d: -d.confianca)
    return achadas


def data_de_apresentacao(texto: str) -> DataAchada | None:
    """A melhor candidata a data DENTRO DE UM TEXTO, ou None.

    Recebe o texto de UMA pagina - normalmente a do carimbo. Nao receba o
    bloco inteiro: a data do fecho ("Plenário ..., 16 de dezembro") entraria
    como se fosse a de apresentacao, e nao e.
    """
    achadas = achar_datas(texto)
    return achadas[0] if achadas else None


# O carimbo da Mesa Diretora, como ele sobrevive ao scanner. Casos reais:
#   "Mesa Diretora | Lido na Sessa©"     "Mesa Diretara | Lido X a SeSSa®"
#   "Mesa Dia etora | Lido na Sessao"    "Mesa [3iret7ra | Lido rº , Sess"
#   "F23 Diretora | Lido na Sessão"      "Liao | na Sessa4"
CARIMBO_SESSAO = re.compile(
    r"l[il1]\w{0,2}o.{0,8}sess|mesa\s*\S{0,4}\s*\w{0,3}etor\w|\bsecret[aá]?r",
    re.IGNORECASE,
)

# O verso e uma folha quase vazia (so carimbo e assinatura). Acima disso a
# pagina tem conteudo demais para ser verso - e a "Secretaria Municipal" do
# corpo do pedido casaria com o regex acima.
DENSIDADE_MAXIMA_VERSO = 350


def achar_pagina_do_carimbo(
    textos: dict[int, str], densidades: dict[int, int],
    pagina_inicial: int, pagina_final: int,
) -> int:
    """Que pagina do bloco mostrar para a pessoa ler a data. 0 se nao houver.

    Comeca DEPOIS da primeira pagina: a folha da indicacao menciona
    "Secretaria Municipal" no proprio pedido e casaria com o regex do carimbo.
    A checagem de densidade e a segunda defesa contra isso.

    Nao achando o carimbo pelo texto, vale a SEGUNDA pagina do bloco - e onde
    o carimbo fica na quase totalidade dos casos. Isso importa porque o verso
    e uma folha quase vazia: as vezes o OCR nao devolve nem o "Lido na
    Sessão" inteiro, e ficar sem imagem nenhuma seria pior do que mostrar a
    pagina certa por posicao. Quem confere e a pessoa, olhando.
    """
    for n in range(pagina_inicial + 1, pagina_final + 1):
        if densidades.get(n, 0) <= DENSIDADE_MAXIMA_VERSO and \
                CARIMBO_SESSAO.search(textos.get(n, "")):
            return n
    return pagina_inicial + 1 if pagina_final > pagina_inicial else 0
