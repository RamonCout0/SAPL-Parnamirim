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

from .config import VERBOS_EMENTA, VERBOS_EMENTA_ANTIGOS

# \b protege o radical: "INDICA" nao casa dentro de "INDICAÇÃO" porque C-cedilha
# e caractere de palavra em modo unicode.
_VERBOS_RE = re.compile(
    r"\b(" + "|".join(v.replace(" ", r"\s+") for v in VERBOS_EMENTA) + r")\b",
    re.IGNORECASE,
)

# Segunda tentativa, so quando a lista principal nao casa nada. Ver o
# comentario de VERBOS_EMENTA_ANTIGOS em config.py.
_VERBOS_ANTIGOS_RE = re.compile(
    r"\b(" + "|".join(v.replace(" ", r"\s+") for v in VERBOS_EMENTA_ANTIGOS) + r")\b",
    re.IGNORECASE,
)

# O papel antigo escreve "JUSTIFICACAO" onde o atual escreve
# "JUSTIFICATIVA". Sem as duas grafias a ementa nao terminava no lugar
# certo e seguia engolindo o texto da justificativa inteira.
FIM_EMENTA_RE = re.compile(r"\bJUSTIFICA(?:TIVA|[ÇC][ÃA]O)\b", re.IGNORECASE)

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


# ---------------------------------------------------------------------- #
# Sinais de OCR estragado DENTRO de uma ementa que saiu "inteira".
#
# A ementa vazia voce ve na hora. A ementa que saiu com o tamanho certo e a
# estrutura certa, mas com "INbICACÁO" no meio, passa batido - e um documento
# oficial nao pode ir assim para o SAPL. Estes avisos existem para a
# conferencia deixar de ser "reler tudo" e virar "olhar onde o programa
# desconfia".
#
# Todas as regras abaixo foram AFERIDAS sobre as 7.840 ementas extraidas dos
# lotes de 2009 a 2020 (26/08/2026), com o numero de acertos ao lado. Regra que
# grita a toa e pior que regra nenhuma: quem recebe aviso demais para de ler
# aviso.
#
# Uma regra foi testada e DESCARTADA: "texto picado", que media a proporcao de
# pedacos de 1 a 2 letras. Marcava 16% das ementas, e o que ela pegava era
# portugues correto - "os indicativos N° 061/2010 e N° 103/2011 junto à
# Presidência da" tem 67% de tokens curtos porque "os", "e", "à", "da" e "N"
# sao palavras de verdade. Nao ha regra de tamanho de palavra que separe
# portugues de lixo.

# Tudo que pode aparecer numa ementa digitada em portugues, pontuacao inclusa.
# Aspas (2.224 ocorrencias) e travessao (1.673) sao pontuacao legitima e nao
# podem virar suspeita - foi por isso que esta lista foi medida, nao chutada.
_CARACTERES_LEGITIMOS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "áàâãéêíóôõúüçÁÀÂÃÉÊÍÓÔÕÚÜÇ"
    "0123456789"
    " \n\t"
    ".,;:()[]{}/-–—%º°ª'\"!?§&+=@#$*"
)

# Digito NO MEIO de uma palavra: o OCR trocou uma letra por um numero parecido
# ("i7a", "M0P", "r1e"). Digito no fim ou no comeco nao entra: "150w" e
# potencia de lampada e "M68" e codigo de rota, os dois legitimos.
_DIGITO_NO_MEIO_RE = re.compile(r"[A-Za-zÀ-ÿ]\d+[A-Za-zÀ-ÿ]")

# Caixa alta com minuscula enfiada no meio: "INbICACÁO", "PAVtMENTAÇÃO".
_CAIXA_MISTURADA_RE = re.compile(r"\b[A-ZÀ-Ý]{2,}[a-zà-ÿ]\w*\b")
# ... menos o plural e o feminino de sigla, que sao escrita normal:
# "UBSs", "ACDs", "EPIs", "PROFa", "SRa".
_SUFIXOS_DE_SIGLA = ("s", "a", "as", "os", "es")

# Palavra de 4+ letras sem nenhuma vogal ("nncfnc", "mptndn", "Fxpr"): o OCR
# embaralhou. Sigla em CAIXA ALTA fica de fora - "SMTT", "CBMRN" e "PMRN" sao
# orgaos de verdade.
_SEM_VOGAL_RE = re.compile(
    r"\b(?![aeiouáàâãéêíóôõúüAEIOUÁÀÂÃÉÊÍÓÔÕÚÜ])"
    r"[bcdfghjklmnpqrstvwxzçBCDFGHJKLMNPQRSTVWXZÇ]{4,}\b"
)

# Quantos exemplos mostrar no aviso. Mais que isso vira parede de texto e
# ninguem le - o objetivo e apontar onde olhar, nao listar tudo.
_MAX_EXEMPLOS = 3


def _amostra(itens: list[str]) -> str:
    unicos = list(dict.fromkeys(itens))
    corte = unicos[:_MAX_EXEMPLOS]
    sufixo = f" +{len(unicos) - _MAX_EXEMPLOS}" if len(unicos) > _MAX_EXEMPLOS else ""
    return ", ".join(corte) + sufixo


def problemas_na_ementa(ementa: str) -> list[str]:
    """Avisos sobre OCR estragado dentro de uma ementa que saiu inteira.

    Devolve frases prontas para a lista de motivos, cada uma ja apontando o
    trecho suspeito. Lista vazia = nada a estranhar.

    Nao julga se a ementa esta CERTA - isso so o papel diz. Julga se ela tem
    marca de OCR quebrado, que e o que da para saber sem olhar o original.
    """
    ementa = (ementa or "").strip()
    if not ementa:
        return []

    avisos: list[str] = []

    estranhos = sorted({c for c in ementa if c not in _CARACTERES_LEGITIMOS})
    if estranhos:
        avisos.append(
            f"ementa: caractere que nao existe em portugues ({_amostra(estranhos)})"
            " - confira no PNG"
        )

    digitos = _DIGITO_NO_MEIO_RE.findall(ementa)
    if digitos:
        avisos.append(
            f"ementa: digito no meio de palavra ({_amostra(digitos)})"
            " - o OCR trocou letra por numero"
        )

    caixa = []
    for t in _CAIXA_MISTURADA_RE.findall(ementa):
        maiusculas = re.match(r"^[A-ZÀ-Ý]+", t).group(0)
        if t[len(maiusculas):] not in _SUFIXOS_DE_SIGLA:
            caixa.append(t)
    if caixa:
        avisos.append(
            f"ementa: maiuscula e minuscula misturadas ({_amostra(caixa)})"
            " - o OCR trocou letra"
        )

    sem_vogal = [t for t in _SEM_VOGAL_RE.findall(ementa) if not t.isupper()]
    if sem_vogal:
        avisos.append(
            f"ementa: palavra sem vogal ({_amostra(sem_vogal)})"
            " - o OCR embaralhou"
        )

    return avisos


def extrair_ementa(texto_bloco: str) -> dict:
    """Retorna {ementa, verbo, metodo, confianca}.

    A ementa sai crua (so com espacos normalizados) para poder ser auditada
    contra o PDF. A versao apresentavel e produzida pelo Ollama depois.
    """
    m_verbo = _VERBOS_RE.search(texto_bloco)
    prefixo_metodo = "verbo"
    if not m_verbo:
        # Modelo antigo do papel ("... a presente Indicacao, SUGERINDO ao
        # Senhor Prefeito ..."). So chega aqui quando nenhum verbo da lista
        # principal casou, entao nada do que ja funcionava muda de resultado.
        #
        # TRAVA: o verbo antigo so vale se estiver ANTES da "Justificativa".
        # Os verbos desta lista sao palavras comuns ("solicita", "sugere") e
        # tambem aparecem no meio do texto da justificacao. Sem esta trava,
        # uma indicacao cujo verbo de verdade o OCR destruiu ("1N,RICA" no
        # lugar de "INDICA", caso real da 42/2010) pescaria um "solicita" la
        # embaixo e produziria uma ementa tirada da justificativa - com
        # confianca 0.9, sem nada denunciando. Ementa errada e pior que
        # ementa vazia: a vazia voce ve na conferencia, a errada passa.
        m_fim = FIM_EMENTA_RE.search(texto_bloco)
        limite = m_fim.start() if m_fim else len(texto_bloco)
        m_antigo = _VERBOS_ANTIGOS_RE.search(texto_bloco)
        if m_antigo and m_antigo.start() < limite:
            m_verbo = m_antigo
            prefixo_metodo = "verbo-antigo"
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
        metodo = f"{prefixo_metodo}..{nome}"
    else:
        bruto = resto[:900]
        metodo = f"{prefixo_metodo}..corte-900"
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
