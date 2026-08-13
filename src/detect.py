"""Etapa 2: achar onde cada indicacao comeca e fatiar o PDF em blocos.

Regra de separacao (conforme especificado):
  a indicacao N comeca na pagina do seu cabecalho e termina na pagina anterior
  ao inicio da PROXIMA indicacao. Assim os casos especiais se resolvem sozinhos:
  se a 101 tem uma pagina extra de fotos, o bloco dela vai de 1 a 3 porque a
  102 so comeca na 4.

O detalhe que quebra a abordagem ingenua e que o OCR do scan falha de tres
formas, todas presentes no documento real:

  1. escreve o cabecalho errado  -> "Indicaçno n° 296/2023"  (regex tolerante)
  2. perde o cabecalho inteiro   -> a pagina 11 nao tem numero nenhum
  3. erra o ano                  -> "Indicação n' 294/ 2022"

Por isso a deteccao usa DOIS sinais independentes:

  SINAL A (numero)     - regex tolerante do cabecalho "Indicação n° N/ANO".
  SINAL B (estrutura)  - a formula de abertura que TODA primeira pagina tem:
                         "vereador com assento nesta egrégia Casa Legislativa".

O sinal B acha a pagina inicial mesmo sem numero legivel; o numero que falta
e deduzido pela posicao na sequencia (ver `inferir_numeros`).
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

from .textlayer import Pagina

# O numero da indicacao, com ou sem separador de milhar.
#
# BUG REAL, achado no lote de 2022: a partir da indicacao 1000 o papel escreve
# "Indicação n° 1.405/2022", com ponto. A versao antiga desta regex exigia os
# digitos colados - (\d{1,4}) - e o pedaco que pula o "n°" ([^0-9\n]) nao pode
# consumir digito, entao nao havia como casar: o cabecalho INTEIRO era
# ignorado. O efeito em cascata era o pior: sem cabecalho, a pagina so era
# reconhecida pela formula de abertura, o numero saia DEDUZIDO pela sequencia,
# e TODA indicacao de numero >= 1000 caia em revisao manual com "numero
# deduzido". Pior ainda, esses buracos entravam no calculo do passo da
# sequencia (ver inferir_numeros) e podiam deduzir numero errado para os
# vizinhos. Aceitar o separador resolve na origem.
#
# A alternativa com separador vem primeiro de proposito: em "1405" ela falha e
# o regex cai na segunda, mas em "1.405" a segunda sozinha pegaria so o "1".
_NUMERO = r"\d{1,3}[.\s]\d{3}|\d{1,4}"

# Tolerante ao OCR: "Indicação n°", "Indicaçno n°", "Indicação no", "Indicação n'".
CABECALHO_RE = re.compile(
    r"INDICA[CÇ]"                # radical estavel
    r"[\wÇÃÁÂÀÉÊÍÓÔÕÚçãáâàéêíóôõú]{0,4}"  # ao / ão / no / cao ...
    r"\s*[Nn]?[^0-9\n]{0,10}"    # n° / nº / n' / no / n. / N.º
    rf"({_NUMERO})\s*[/\-]\s*(\d{{4}})",
    re.IGNORECASE,
)


def numero_do_cabecalho(bruto: str) -> int:
    """"1.405" / "1 405" / "1405" -> 1405.

    O separador de milhar e do papel; o numero da indicacao e um inteiro so.
    Tudo que sai da CABECALHO_RE passa por aqui - nunca int() direto, senao
    "1.405" viraria ValueError ou, pior, um numero truncado.
    """
    return int(re.sub(r"[.\s]", "", bruto))

# Um cabecalho legitimo esta no topo da pagina. Mais fundo que isso e citacao
# no corpo do texto ("REITERA a indicação n° 498/2022"), que NAO abre bloco.
# Atencao: varias citacoes caem DENTRO dessa janela (posicao ~200), entao a
# regra que realmente decide e "vale o primeiro cabecalho da pagina".
JANELA_CABECALHO = 400

# Paginas de anexo repetem o numero da indicacao a que pertencem:
#   "ANEXO / Anexo à Indicação n° 233/2023. Registro fotográfico (demanda)..."
# Elas sao CONTINUACAO do bloco, nunca um inicio - se contadas como inicio,
# a indicacao aparece duplicada.
MARCADORES_ANEXO = ["anexo", "registro fotogr"]

# Formula de abertura. Presente na 1a pagina de toda indicacao, mesmo quando o
# cabecalho com o numero foi perdido pelo OCR.
MARCADORES_INICIO = [
    "assento nesta egr",          # "vereador com assento nesta egrégia Casa"
    "forma regimental",           # "subscrito na forma regimental em vigência"
    "casa legislativa",
]

# Em paginas de abertura real, esses marcadores aparecem bem cedo (medido:
# 108-214 caracteres). "casa legislativa" sozinho e perigoso porque tambem
# aparece em frases do CORPO da justificativa - "para que esta Casa
# Legislativa dê início ao debate..." - bem mais tarde no texto (medido: 374).
# Isso fez uma pagina de CONTINUACAO (justificativa + assinatura, sem verbo
# de abertura nenhum) ser lida como inicio de uma indicacao nova. Por isso o
# marcador so conta se aparecer perto do topo da pagina.
JANELA_MARCADOR_INICIO = 280

# Paginas de verso: a folha com o carimbo "Lido na Sessão" e a data.
MARCADORES_VERSO = [
    "lido na sess",
    "mesa diretora",
    "secretário",
    "secretario",
    "recebido",
]

# Abaixo disso a pagina nao tem texto suficiente para ser uma 1a pagina.
DENSIDADE_MINIMA_INICIO = 350

# Quanto um numero pode destoar dos vizinhos sem virar suspeita.
#
# Buracos de verdade existem (indicacao que simplesmente nao esta no lote), mas
# sao de poucas unidades. Erro de OCR em numero de quatro digitos erra por
# centenas ou milhares - casos reais do lote de 2021:
#   "Indicacao n° /617/2021"      -> leu 617,  era 1617  (erro de 1000)
#   "INDICAcAO N°. iG l9 / 2021"  -> leu 9,    era 1629  (erro de 1620)
# Uma folga de 20 passa longe dos buracos legitimos e pega esses de longe.
TOLERANCIA_SEQUENCIA = 20

# Quantos vizinhos olhar de cada lado. Dois, e nao um: com um so, um numero
# bom encostado num numero ruim era acusado junto com ele.
VIZINHOS_CONSIDERADOS = 2


@dataclass
class Inicio:
    """Uma pagina identificada como comeco de indicacao."""

    pagina: int
    numero: int | None       # None quando o OCR perdeu o cabecalho
    ano: int | None
    tem_cabecalho: bool
    tem_estrutura: bool
    numero_inferido: bool = False
    # O numero foi lido, mas nao conversa com nenhum vizinho da sequencia -
    # quase sempre OCR destruido no cabecalho. Ver marcar_suspeitos.
    numero_suspeito: bool = False


@dataclass
class Bloco:
    numero: int
    ano: int
    pagina_inicial: int
    pagina_final: int
    numero_inferido: bool = False
    numero_suspeito: bool = False
    avisos: list[str] = field(default_factory=list)

    @property
    def identificador(self) -> str:
        return f"{self.numero}/{self.ano}"

    @property
    def qtd_paginas(self) -> int:
        return self.pagina_final - self.pagina_inicial + 1

    @property
    def faixa(self) -> str:
        if self.pagina_inicial == self.pagina_final:
            return str(self.pagina_inicial)
        return f"{self.pagina_inicial}-{self.pagina_final}"


def _tem(texto: str, marcadores: list[str]) -> bool:
    baixo = texto.lower()
    return any(m in baixo for m in marcadores)


def _tem_estrutura_de_abertura(texto: str) -> bool:
    """MARCADORES_INICIO, mas so contam perto do topo da pagina - ver
    JANELA_MARCADOR_INICIO para o caso real que motivou isto."""
    baixo = texto[:JANELA_MARCADOR_INICIO].lower()
    return any(m in baixo for m in MARCADORES_INICIO)


def classificar_paginas(
    paginas: list[Pagina],
) -> tuple[list[Inicio], list[dict]]:
    """Decide, pagina por pagina, se ela abre uma indicacao nova.

    Retorna (inicios, citacoes_ignoradas).
    """
    inicios: list[Inicio] = []
    citacoes: list[dict] = []
    ultimo_numero: int | None = None

    for p in paginas:
        cab = None
        for m in CABECALHO_RE.finditer(p.texto):
            # "Anexo à Indicação n° 233/2023" logo antes do numero denuncia
            # pagina de anexo fotografico, que pertence ao bloco anterior.
            antes = p.texto[max(0, m.start() - 60) : m.start()].lower()
            eh_anexo = any(k in antes for k in MARCADORES_ANEXO)

            if cab is None and m.start() <= JANELA_CABECALHO and not eh_anexo:
                cab = m
                continue

            if eh_anexo:
                motivo = "anexo da propria indicacao"
            elif cab is not None:
                motivo = "citacao (o cabecalho da pagina ja foi lido)"
            else:
                motivo = "fundo da pagina"
            citacoes.append(
                {
                    "pagina": p.numero,
                    "numero": numero_do_cabecalho(m.group(1)),
                    "ano": int(m.group(2)),
                    "motivo": motivo,
                    "trecho": p.texto[
                        max(0, m.start() - 60) : m.start() + 90
                    ].replace("\n", " "),
                }
            )

        estrutura = _tem_estrutura_de_abertura(p.texto)
        verso = _tem(p.texto, MARCADORES_VERSO) and p.densidade < DENSIDADE_MINIMA_INICIO
        anexo_no_topo = any(k in p.texto[:200].lower() for k in MARCADORES_ANEXO)

        # "Cartao-resumo": uma pagina de formato bem diferente (linhas curtas
        # "INDICAÇÃO: N/ANO - data - orgao" / "VEREADOR(A): nome" /
        # "SOLICITAÇÃO: ...") que a assessoria de alguns vereadores anexa
        # DEPOIS da propria indicacao, repetindo o mesmo numero. Sem essa
        # checagem ela e lida como um novo inicio identico ao anterior, e a
        # mesma indicacao vira dois blocos. O sinal e: cabecalho bate mas SEM
        # a formula juridica de abertura, e o numero repete o do inicio
        # imediatamente anterior - um numero diferente aqui provavelmente e
        # coisa nova de verdade e continua sendo tratado como inicio.
        eh_cartao_resumo = (
            cab is not None
            and not estrutura
            and ultimo_numero is not None
            and numero_do_cabecalho(cab.group(1)) == ultimo_numero
        )

        # Abre bloco se: tem cabecalho no topo (e nao for cartao-resumo), OU
        # tem a formula de abertura com texto suficiente (caso do cabecalho
        # perdido pelo OCR).
        if cab is not None and not eh_cartao_resumo:
            inicios.append(
                Inicio(
                    pagina=p.numero,
                    numero=numero_do_cabecalho(cab.group(1)),
                    ano=int(cab.group(2)),
                    tem_cabecalho=True,
                    tem_estrutura=estrutura,
                )
            )
            ultimo_numero = numero_do_cabecalho(cab.group(1))
        elif eh_cartao_resumo:
            citacoes.append(
                {
                    "pagina": p.numero,
                    "numero": numero_do_cabecalho(cab.group(1)),
                    "ano": int(cab.group(2)),
                    "motivo": "cartao-resumo da mesma indicacao (nao abre bloco novo)",
                    "trecho": p.texto[:150].replace("\n", " "),
                }
            )
        elif (
            estrutura
            and not verso
            and not anexo_no_topo
            and p.densidade >= DENSIDADE_MINIMA_INICIO
        ):
            inicios.append(
                Inicio(
                    pagina=p.numero,
                    numero=None,
                    ano=None,
                    tem_cabecalho=False,
                    tem_estrutura=True,
                )
            )
            ultimo_numero = None

    return inicios, citacoes


def _passo_da_sequencia(conhecidos: list[tuple[int, int]]) -> int:
    """De quanto em quanto os numeros andam. Mediana, nao media: um numero
    lido errado desloca a media e nao mexe na mediana."""
    passos = [
        (n2 - n1) / (i2 - i1)
        for (i1, n1), (i2, n2) in zip(conhecidos, conhecidos[1:])
        if i2 != i1
    ]
    return round(statistics.median(passos)) if passos else -1


def marcar_suspeitos(inicios: list[Inicio]) -> list[Inicio]:
    """Marca numeros lidos que nao conversam com NENHUM vizinho.

    O caso real que motivou isto: o OCR leu "iG l9" onde estava "1.629" e o
    sistema registrou a indicacao como numero 9. Ela passou em todos os
    criterios (ementa boa, autor resolvido) e foi classificada como PRONTA -
    ou seja, iria para o SAPL como "Indicacao 9/2021", um registro oficial
    errado, sem ninguem ver. Numero fora da sequencia era so um aviso
    decorativo que nada lia.

    A regra e deliberadamente conservadora: so vira suspeita quem discorda de
    TODOS os vizinhos da janela. Duas consequencias que importam:

      - uma virada legitima de sequencia nao acusa nada. O lote real de 2021
        tem uma (...792, 793, depois 601, 602...): cada um concorda com o seu
        proprio lado.
      - o vizinho ruim nao derruba o bom. Olhar so o vizinho colado fazia o
        1628 ser acusado por estar ao lado do 9; com dois de cada lado ele
        encontra o 1630 e se confirma.
    """
    conhecidos = [
        (i, ini.numero) for i, ini in enumerate(inicios)
        if ini.numero is not None and not ini.numero_inferido
    ]
    if len(conhecidos) < 3:
        return inicios  # sequencia curta demais para saber o que e desvio

    passo = _passo_da_sequencia(conhecidos)
    for posicao, (i, numero) in enumerate(conhecidos):
        vizinhos = (
            conhecidos[max(0, posicao - VIZINHOS_CONSIDERADOS):posicao]
            + conhecidos[posicao + 1:posicao + 1 + VIZINHOS_CONSIDERADOS]
        )
        distancias = [
            abs(numero - (n + passo * (i - j))) for j, n in vizinhos
        ]
        if distancias and min(distancias) > TOLERANCIA_SEQUENCIA:
            inicios[i].numero_suspeito = True
    return inicios


def inferir_numeros(inicios: list[Inicio], ano_padrao: int) -> list[Inicio]:
    """Deduz os numeros perdidos pelo OCR a partir da posicao na sequencia.

    O documento vem numa progressao regular (aqui, decrescente de 1 em 1).
    Achamos o passo pelos vizinhos conhecidos e projetamos sobre os buracos.

    Os numeros suspeitos ficam de fora das ancoras: um erro de leitura nao
    pode contaminar as vizinhas. Foi o que aconteceu no lote de 2021 - o "9"
    lido por engano virou ancora e a indicacao seguinte, cujo cabecalho o OCR
    perdeu de vez, foi deduzida como "10" em vez de 1630.
    """
    conhecidos = [
        (i, ini.numero) for i, ini in enumerate(inicios)
        if ini.numero and not ini.numero_suspeito
    ]
    if len(conhecidos) < 2:
        return inicios

    passo = _passo_da_sequencia(conhecidos) or -1

    for i, ini in enumerate(inicios):
        if ini.numero is not None:
            continue
        # Ancora no vizinho conhecido mais proximo.
        anterior = [(j, n) for j, n in conhecidos if j < i]
        seguinte = [(j, n) for j, n in conhecidos if j > i]
        candidatos = []
        if anterior:
            j, n = anterior[-1]
            candidatos.append(n + passo * (i - j))
        if seguinte:
            j, n = seguinte[0]
            candidatos.append(n + passo * (i - j))
        if candidatos and all(c == candidatos[0] for c in candidatos):
            ini.numero = candidatos[0]
            ini.ano = ano_padrao
            ini.numero_inferido = True
        elif candidatos:
            # Vizinhos discordam: fica o do lado anterior, mas marcado.
            ini.numero = candidatos[0]
            ini.ano = ano_padrao
            ini.numero_inferido = True

    return inicios


def montar_blocos(
    inicios: list[Inicio], total_paginas: int, ano_padrao: int
) -> list[Bloco]:
    """Cada inicio manda ate a pagina anterior ao proximo inicio."""
    blocos: list[Bloco] = []
    for i, ini in enumerate(inicios):
        if ini.numero is None:
            continue
        fim = inicios[i + 1].pagina - 1 if i + 1 < len(inicios) else total_paginas
        avisos: list[str] = []

        # O ano do cabecalho e ruido de OCR frequente ("294/ 2022" onde o
        # documento todo e de 2023). O ano do lote manda.
        ano = ini.ano or ano_padrao
        if ano != ano_padrao:
            avisos.append(f"OCR leu ano {ano}; corrigido para {ano_padrao}")
            ano = ano_padrao

        if ini.numero_inferido:
            avisos.append("numero DEDUZIDO pela sequencia (cabecalho ilegivel) - confirmar")

        blocos.append(
            Bloco(
                numero=ini.numero,
                ano=ano,
                pagina_inicial=ini.pagina,
                pagina_final=fim,
                numero_inferido=ini.numero_inferido,
                numero_suspeito=ini.numero_suspeito,
                avisos=avisos,
            )
        )
    return blocos


def auditar(blocos: list[Bloco]) -> list[Bloco]:
    """Marca o que precisa de olho humano antes de subir pro SAPL."""
    vistos: dict[int, int] = {}
    for i, b in enumerate(blocos):
        if b.numero in vistos:
            b.avisos.append(f"numero repetido (ja visto na pagina {vistos[b.numero]})")
        vistos[b.numero] = b.pagina_inicial

        if b.qtd_paginas > 4:
            b.avisos.append(f"{b.qtd_paginas} paginas - conferir se falta um inicio")
        if b.qtd_paginas == 1:
            b.avisos.append("1 pagina - verso pode nao ter sido escaneado")

        if i + 1 < len(blocos):
            passo = blocos[i + 1].numero - b.numero
            if passo not in (1, -1):
                b.avisos.append(f"sequencia salta para {blocos[i+1].numero}")

    numeros = [b.numero for b in blocos]
    if numeros:
        faltando = sorted(set(range(min(numeros), max(numeros) + 1)) - set(numeros))
        if faltando:
            blocos[0].avisos.append(
                "ausentes no documento: " + ", ".join(map(str, faltando))
            )
    return blocos
