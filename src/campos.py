"""Etapa 3: tirar do texto do bloco a ementa e o nome do autor.

A ementa comeca depois do verbo (INDICA / INDICAR / REITERA / RETIRA /
VEM INDICAR ...) e termina na palavra "Justificativa".

O nome do autor vem imediatamente antes de "vereador(a)":
    "Wolney Freitas de Azevedo França, vereador com assento nesta egrégia..."
    "O Vereador Lindovaildo Soares de Azevedo — VAVÁ AZEVEDO, com assento..."

Tudo aqui e regex/heuristica: rapido, deterministico e auditavel. O Ollama
entra depois (ver ollama_client.py) para (a) limpar o portugues estragado pelo
OCR, (b) achar a ementa quando o OCR comeu o verbo e (c) casar o nome civil
com o nome do select do SAPL.
"""
from __future__ import annotations

import re

from .config import VERBOS_EMENTA

# \b protege o radical: "INDICA" nao casa dentro de "INDICAÇÃO" porque C-cedilha
# e caractere de palavra em modo unicode.
_VERBOS_RE = re.compile(
    r"\b(" + "|".join(v.replace(" ", r"\s+") for v in VERBOS_EMENTA) + r")\b",
    re.IGNORECASE,
)

FIM_EMENTA_RE = re.compile(r"\bJUSTIFICATIVA\b", re.IGNORECASE)

# Quando o OCR perde a palavra "Justificativa", estes marcam onde a ementa
# certamente ja acabou (abertura da justificativa, fecho ou rodape).
FIM_ALTERNATIVO_RE = re.compile(
    r"\b(?:Atendendo\s+aos|Agradecemos|Plen[aá]rio\s+(?:Dr|br|Vereador)|"
    r"Sala\s+das\s+Sess|Nestes\s+termos|Valho-me)\b",
    re.IGNORECASE,
)

# Sujeira de carimbo/rodape que o OCR intercala no meio do texto. A ementa
# termina no primeiro destes que aparecer.
RUIDO_FIM_RE = re.compile(
    r"(?:RECEBIDO|DEPARTAMENTO|PROCESSO\s+LEGISLATIVO|Mesa\s+Diretora|"
    r"Lido\s+na\s+Sess|Avenida\s+Castor|Av\.\s+Castor|Site:|Telefones?:|"
    r"Vereador\s+Autor|CÂMARA\s+MUNICIPAL|CAMARA\s+MUNICIPAL)",
    re.IGNORECASE,
)

# Linhas de saudacao que precedem o nome do autor. Se ficarem na janela de
# busca, o regex captura "Senhores" em vez do nome.
SAUDACAO_RE = re.compile(
    r"^\s*(?:Senhor(?:es)?\s+Presidente|Senhor(?:es)?\s+Vereador(?:es|as)?|"
    r"Nobres\s+Vereador(?:es|as)?|Senhoras?\s+e\s+Senhores|Excelent[íi]ssimo)"
    r"[\s,.:;]*$",
    re.IGNORECASE,
)

# "Nome do Autor, vereador com assento..."  ->  captura o nome.
#
# vereador[ae]?\b nao casa "Vereadores" (plural da saudacao), porque depois de
# "vereador" vem "e" e depois de "vereadore" vem "s", ambos sem fronteira.
#
# [^\S\n] e "espaco que nao e quebra de linha": prende o nome a UMA linha. Sem
# isso a captura pula a linha e engole o cabecalho seguinte, produzindo
# "JOSÉ AFRÂNIO BEZERRA DA SILVA Indicação no".
# ATENCAO: estas regex NAO levam re.IGNORECASE. A flag global anularia a
# exigencia de inicial maiuscula do _TOKEN, e a captura passaria a pegar
# "com assento nesta egrégia Casa Legislativa" como se fosse nome proprio.
# So a palavra "vereador" e case-insensitive, via flag escopada (?i:...).
_ESP = r"[^\S\n]"
_TOKEN = r"[A-ZÀ-Ý][\wÀ-ÿ'.\-]*"
_VEREADOR = r"(?i:vereador[ae]?)"

AUTOR_ANTES_RE = re.compile(
    rf"({_TOKEN}(?:{_ESP}+(?:d[aeo]s?|e|—|-)?{_ESP}*{_TOKEN}){{1,6}})"
    rf"{_ESP}*,?\s*{_VEREADOR}\b"
)
AUTOR_DEPOIS_RE = re.compile(
    rf"\b{_VEREADOR}\b(?:{_ESP}|,)*({_TOKEN}"
    rf"(?:{_ESP}+(?:d[aeo]s?|e)?{_ESP}*{_TOKEN}){{1,6}})"
)

# Palavras do timbre/carimbo que nunca fazem parte de um nome de vereador.
LIXO_NOME_RE = re.compile(
    r"^(?:PROC|CASA|POVO|SR|SRA|EXMO|EXMA|PARNAMIRIM|PARNAM|RIM|C[ÂA]MARA|"
    r"MUNICIPAL|RECEBIDO|ANEXO|MESA|DIRETORA|SENHOR(?:ES)?|NOBRES|"
    r"VEREADOR(?:ES|AS)?|GABINETE|ASSESSORIA|PRESIDENTE|DEPARTAMENTO|"
    r"PROCESSO|LEGISLATIVO|SECRETARIA|PROTOCOLO|INDICA[CÇ][AÃ]O)$",
    re.IGNORECASE,
)
# Token com maiusculas e uma minuscula no meio: "PFtOC", "CiA", tipico de OCR.
TOKEN_MISTO_RE = re.compile(r"[A-ZÀ-Ý]{2,}[a-zà-ÿ]")
# Preposicoes que ligam partes do nome: validas no meio, nunca nas pontas.
CONECTORES = {"de", "da", "do", "das", "dos", "e"}
# Apelido em caixa alta entre parenteses ou depois de travessao:
#   "Lindovaildo Soares de Azevedo — VAVÁ AZEVEDO"  /  "(VAVÁ AZEVEDO)"
APELIDO_RE = re.compile(r"[—\-(]\s*([A-ZÀ-Ý][A-ZÀ-Ý\s'.]{4,40})\s*[)\n,]")

# Siglas de orgao que a regex de apelido pesca por engano.
NAO_E_APELIDO_RE = re.compile(
    r"CÂMARA|CAMARA|MUNICIPAL|SECRETARIA|PARNAMIRIM|RECEBIDO|SEMOP|SEMSUR|"
    r"SELIM|SEMUR|SEMEC|SEARH|SEPLAF|SESAD|SESDEM|GACIV|UBS|POVO|CASA|"
    r"AMENTO|PROCESSO|LEGISLATIVO|PROTOCOLO|GABINETE|PRESIDENTE|DIRETORA",
    re.IGNORECASE,
)


def _normalizar_espacos(texto: str) -> str:
    """Junta as quebras de linha do OCR num paragrafo unico."""
    texto = re.sub(r"-\n(\w)", r"\1", texto)      # hifenizacao de fim de linha
    texto = re.sub(r"\s*\n\s*", " ", texto)
    texto = re.sub(r"\s{2,}", " ", texto)
    return texto.strip(" ,;.:-–—\t")


def extrair_ementa(texto_bloco: str) -> dict:
    """Retorna {ementa, verbo, metodo, confianca}.

    A ementa sai crua (so com espacos normalizados) para poder ser auditada
    contra o PDF. A versao apresentavel e produzida pelo Ollama depois.
    """
    m_verbo = _VERBOS_RE.search(texto_bloco)
    if not m_verbo:
        return {"ementa": "", "verbo": None, "metodo": "sem-verbo", "confianca": 0.0}

    inicio = m_verbo.end()
    resto = texto_bloco[inicio:]

    # Onde a ementa termina: o primeiro limite que aparecer.
    limites = []
    for regex, nome, conf in (
        (FIM_EMENTA_RE, "justificativa", 0.9),
        (FIM_ALTERNATIVO_RE, "fim-alternativo", 0.65),
        (RUIDO_FIM_RE, "ruido-rodape", 0.6),
    ):
        m = regex.search(resto)
        if m:
            limites.append((m.start(), nome, conf))

    if limites:
        corte, nome, confianca = min(limites)
        bruto = resto[:corte]
        metodo = f"verbo..{nome}"
    else:
        bruto = resto[:900]
        metodo = "verbo..corte-900"
        confianca = 0.4

    ementa = _normalizar_espacos(bruto)
    if len(ementa) < 30:
        confianca = min(confianca, 0.25)
    elif len(ementa) > 800:
        confianca = min(confianca, 0.5)

    return {
        "ementa": ementa,
        "verbo": m_verbo.group(1).upper(),
        "metodo": metodo,
        "confianca": round(confianca, 2),
    }


def _janela_autor(texto_bloco: str) -> str:
    """Primeiras linhas sem as saudacoes, que confundiriam a busca do nome."""
    linhas = [l for l in texto_bloco[:1500].splitlines() if not SAUDACAO_RE.match(l)]
    return "\n".join(linhas)


def _token_de_nome(t: str) -> bool:
    """Um token pode fazer parte de um nome proprio?"""
    if any(c.isdigit() for c in t):                 # "PR0CE", "a-023"
        return False
    # Duas letras so valem como preposicao ("de", "da"). "no", "vt" e lixo.
    if len(t) < 3 and t.lower() not in CONECTORES:
        return False
    if LIXO_NOME_RE.match(t):                       # "GABINETE", "PROC"
        return False
    if TOKEN_MISTO_RE.search(t):                    # "PFtOC"
        return False
    return all(c.isalpha() or c in "'-." for c in t)


def _limpar_nome(nome: str) -> str:
    """Fica com o nome, descartando o lixo do OCR.

    Varre da DIREITA para a esquerda: o nome esta encostado no ", vereador",
    e todo o entulho de carimbo ("ÁME p PR0CE", "DEPARTAMENTO DD PROCe4")
    aparece antes dele. Parar no primeiro token invalido resolve os dois casos.
    """
    bons: list[str] = []
    for token in reversed(nome.split()):
        t = token.strip(".,;:")
        if not _token_de_nome(t):
            break
        bons.append(t)
        if len(bons) >= 7:
            break
    tokens = list(reversed(bons))

    # Conector solto na ponta nao e nome ("do", "de").
    while tokens and tokens[0].lower() in CONECTORES:
        tokens.pop(0)
    while tokens and tokens[-1].lower() in CONECTORES:
        tokens.pop()
    return " ".join(tokens)


def _nome_plausivel(nome: str) -> bool:
    return len(nome) >= 6 and len(nome.split()) >= 2


def extrair_nome_autor(texto_bloco: str) -> dict:
    """Retorna {nome, apelido, metodo}. O casamento com o ID fica em autores.py."""
    janela = _janela_autor(texto_bloco)

    # Percorre TODAS as ocorrencias das duas leituras, nao so a primeira.
    # Em "Gabinete do Vereador JOSÉ AFRÂNIO ... / José Afrânio Bezerra da
    # Silva, Vereador com assento", a primeira ocorrencia entrega "Gabinete
    # do" e o nome de verdade esta na segunda.
    tentativas = []
    for regex, origem in (
        (AUTOR_ANTES_RE, "antes-de-vereador"),
        (AUTOR_DEPOIS_RE, "depois-de-vereador"),
    ):
        for m in list(regex.finditer(janela))[:6]:
            tentativas.append((origem, m.group(1)))

    nome, metodo = "", "falhou"
    for origem, bruto in tentativas:
        candidato = _limpar_nome(
            re.sub(r"\s+vereador[ae]?$", "", _normalizar_espacos(bruto),
                   flags=re.IGNORECASE)
        )
        if _nome_plausivel(candidato):
            nome, metodo = candidato, origem
            break
        if candidato and not nome:      # guarda o melhor palpite fraco
            nome, metodo = candidato, f"{origem}-fraco"

    apelido = ""
    for m_ap in list(APELIDO_RE.finditer(janela))[:4]:
        candidato = _normalizar_espacos(m_ap.group(1))
        if _apelido_plausivel(candidato):
            apelido = candidato
            break

    return {"nome": nome, "apelido": apelido, "metodo": metodo}


def _apelido_plausivel(candidato: str) -> bool:
    """Apelido de vereador tem 1 a 3 palavras e nada de sigla de orgao.

    Sem isso o regex pesca carimbo: "IJEP PTAMENTO DO PROCESSO", "SESDEM".
    """
    tokens = candidato.split()
    if not 1 <= len(tokens) <= 3:
        return False
    if NAO_E_APELIDO_RE.search(candidato):
        return False
    return all(_token_de_nome(t.strip(".,;:")) for t in tokens)
