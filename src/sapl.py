"""Preenchimento do formulario do SAPL - a logica, sem a tela.

Este modulo nao imprime nada nem pergunta nada. Quem conversa com a pessoa e
quem chama: scripts/02_preencher_sapl.py (terminal) e gui/tela_sapl.py
(interface). Os dois preenchem exatamente do mesmo jeito porque usam as
mesmas funcoes daqui - se a regra mudar, muda para os dois de uma vez.

O que este modulo NUNCA faz, de proposito:

  - salvar a indicacao no SAPL. Ele preenche e para; conferir e salvar e
    decisao de gente.
  - digitar senha. O login e feito por voce na janela que abre, e fica
    guardado no perfil do navegador para as proximas vezes.
  - preencher a data de apresentacao e anexar o PDF. Ficaram manuais por
    decisao do orgao - a interface mostra os dois valores prontos para copiar.
"""
from __future__ import annotations

from pathlib import Path

from .config import CONFIG_DIR, RAIZ

# Perfil proprio do Playwright: guarda o cookie de sessao do SAPL para nao
# precisar logar toda vez. Esta no .gitignore - e credencial.
PERFIL = RAIZ / ".perfil_navegador"


def carregar_form() -> dict:
    import json

    return json.loads((CONFIG_DIR / "sapl_form.json").read_text(encoding="utf-8"))


def achar(pagina, candidatos: list[str]):
    """Primeiro seletor que existir de verdade na pagina."""
    for sel in candidatos:
        alvo = pagina.locator(sel)
        try:
            if alvo.count() > 0:
                return alvo.first
        except Exception:
            continue
    return None


def definir_select(pagina, alvo, valor: str) -> bool:
    """Escolhe uma opcao. Cai para JS quando o SAPL esconde o select (select2)."""
    try:
        alvo.select_option(value=str(valor), timeout=4000)
        return True
    except Exception:
        pass
    try:
        # select2 mantem o <select> nativo oculto: mexe nele e avisa a pagina.
        alvo.evaluate(
            """(el, v) => {
                el.value = v;
                el.dispatchEvent(new Event('input',  {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                if (window.jQuery) jQuery(el).trigger('change');
            }""",
            str(valor),
        )
        return alvo.input_value() == str(valor)
    except Exception:
        return False


def definir_texto(alvo, valor: str) -> bool:
    try:
        alvo.fill(str(valor), timeout=4000)
        return True
    except Exception:
        return False


def pagina_valida(nav, pagina):
    """Devolve uma pagina utilizavel. Se a atual foi fechada (janela fechada
    a mao, crash por ficar muito tempo em segundo plano etc.), reaproveita
    outra aba aberta no mesmo contexto ou abre uma nova - sem isso, qualquer
    fechamento acidental da janela derrubava a sessao inteira."""
    from playwright.sync_api import Error as PlaywrightError

    try:
        if not pagina.is_closed():
            return pagina
    except PlaywrightError:
        pass
    for p in nav.pages:
        try:
            if not p.is_closed():
                return p
        except PlaywrightError:
            continue
    return nav.new_page()


def descobrir_rotas(pagina, base: str) -> list[str]:
    """Lista as rotas de materia visiveis depois do login.

    O SAPL responde 404 (nao 302) nas telas de CRUD quando o usuario nao tem
    permissao, entao so da para confirmar o caminho do formulario estando
    logado. Se o caminho do config estiver errado, isto mostra o certo.
    """
    achadas: set[str] = set()
    for caminho in ("/", "/materia/", "/sistema/"):
        try:
            pagina.goto(base + caminho, wait_until="domcontentloaded", timeout=20000)
        except Exception:
            continue
        for href in pagina.eval_on_selector_all(
            "a[href]", "els => els.map(e => e.getAttribute('href'))"
        ):
            if href and "materia" in href and href.startswith("/"):
                achadas.add(href.split("?")[0])
    return sorted(achadas)


def listar_campos(pagina) -> list[dict]:
    """Todos os campos reais do formulario - para descobrir os ids quando o
    SAPL de outra Camara usa nomes diferentes dos do sapl_form.json."""
    return pagina.evaluate(
        """() => [...document.querySelectorAll('input, select, textarea')].map(e => ({
              tag: e.tagName.toLowerCase(),
              tipo: e.type || '',
              id: e.id || '',
              name: e.name || '',
              rotulo: (document.querySelector(`label[for="${e.id}"]`)||{}).innerText || ''
           }))"""
    )


def preencher(pagina, form: dict, ind: dict) -> tuple[list[str], list[str]]:
    """Preenche os campos automaticos. Retorna (falhas, notas).

    falhas: problema de configuracao de verdade - vale rodar --inspecionar.
    notas: esperado, precisa de atencao manual, mas NAO e bug de config.
    """
    campos = form["campos"]
    falhas = []
    notas = []

    # "numero" fica por ULTIMO de proposito. O formulario do SAPL sugere
    # automaticamente o "proximo numero disponivel" assim que tipo_materia e
    # ano sao escolhidos - via requisicao assincrona que so volta depois do
    # nosso fill. Se numero for preenchido antes desses dois, a sugestao do
    # SAPL chega em seguida e sobrescreve o que preenchemos (foi o que
    # aconteceu: o campo sempre ficava com o ultimo numero da sequencia geral,
    # tipo 1946, em vez do numero da indicacao).
    plano = [
        ("tipo_materia", "select", ind["tipo_materia_id"]),
        ("ano", "select", ind["ano"]),
        ("regime_tramitacao", "select", ind["regime_id"]),
        ("tipo_apresentacao", "select", ind["tipo_apresentacao"]),
        # A data vem ANTES do autor de proposito: o SAPL so libera as opcoes
        # do select "Autor" depois que a data existe, porque filtra por quem
        # estava no mandato naquela data. Com a ordem invertida, o autor
        # simplesmente nunca preenchia - era o aviso "autor nao
        # pre-selecionado" que aparecia em toda indicacao.
        ("data_apresentacao", "texto", ind.get("data_apresentacao", "")),
        # A ementa vai em CAIXA ALTA para o SAPL - convencao do orgao. O
        # texto guardado em indicacoes.json/csv fica como foi extraido (para
        # servir de comparacao com o PDF original); a maiusculizacao e so
        # nesta hora, ao escrever na tela.
        ("ementa", "texto", ind["ementa"].upper()),
        ("tipo_autor", "select", ind["tipo_autor_id"]),
        ("autor", "select", ind["autor_id"]),
        ("numero", "texto", ind["numero"]),
    ]

    for nome, especie, valor in plano:
        if nome == "data_apresentacao" and not str(valor).strip():
            # Sem data nao ha o que preencher - e sem ela o autor tambem nao
            # abre. A indicacao nao devia ter chegado ate aqui: o criterio de
            # "pronto" exige data. Avisa em vez de preencher vazio.
            falhas.append(
                "data de apresentação em branco - preencha na aba de "
                "conferência (ela está no carimbo do verso)")
            continue

        alvo = achar(pagina, campos.get(nome, []))
        if alvo is None:
            falhas.append(f"{nome}: campo nao encontrado na pagina")
            continue
        # "ano" as vezes e select, as vezes input, dependendo da versao.
        marca = alvo.evaluate("e => e.tagName.toLowerCase()")
        if marca == "select":
            ok = definir_select(pagina, alvo, valor)
        else:
            ok = definir_texto(alvo, valor)
        if not ok:
            if nome == "autor":
                # Agora que a data e preenchida ANTES, o autor deveria abrir.
                # Se mesmo assim nao aceitou, o mais provavel e que esse
                # vereador nao estivesse no mandato naquela data - ou seja, a
                # data ou o autor esta errado. Vale conferir os dois no papel
                # antes de escolher a mao.
                notas.append(
                    f"autor não aceito: o SAPL filtra por quem estava no "
                    f"mandato em {ind.get('data_apresentacao') or 'nesta data'} "
                    f"— confira a data e escolha à mão: "
                    f"{ind['autor_nome_sapl']} (id {ind['autor_id']})"
                )
            else:
                falhas.append(f"{nome}: nao aceitou o valor {valor!r}")

        # Depois de tipo_materia/ano, a sugestao automatica do SAPL pode
        # demorar um instante para chegar e reescrever o campo numero. Espera
        # aqui em vez de so no final, para o numero (preenchido por ultimo)
        # nao ser pego por uma sugestao ainda em transito.
        #
        # Depois da data, a espera e por outro motivo: o SAPL recarrega a
        # lista de autores filtrando pelo mandato vigente naquela data, e
        # escolher o autor antes disso chegar nao pega.
        if nome in ("tipo_materia", "ano", "data_apresentacao"):
            pagina.wait_for_timeout(1200)

    # O anexo por ultimo: e o campo mais lento (sobe arquivo) e nao influencia
    # nenhum outro. Um input de arquivo nao aceita fill() - so set_input_files.
    caminho = caminho_do_pdf(ind)
    alvo_anexo = achar(pagina, campos.get("texto_original", []))
    if alvo_anexo is None:
        notas.append("campo de anexo não encontrado - anexe o PDF à mão")
    elif not caminho.is_file():
        # Some quando voce ja anexou e apagou o arquivo: e o jeito que o
        # sistema entende "essa ja foi enviada". Nao e erro.
        notas.append(
            f"{caminho.name} não está mais em output\\pdfs - se você já "
            "cadastrou esta indicação, ignore")
    else:
        try:
            alvo_anexo.set_input_files(str(caminho), timeout=15000)
        except Exception as e:
            falhas.append(f"anexo: nao deu para anexar {caminho.name} ({e})")

    # Confere que o numero realmente ficou com o valor certo depois de tudo -
    # se algum outro evento da pagina ainda sobrescrever, isso aparece aqui em
    # vez de passar batido para a tela que o usuario confere visualmente.
    alvo_numero = achar(pagina, campos.get("numero", []))
    if alvo_numero is not None:
        atual = alvo_numero.input_value()
        if str(atual).strip() != str(ind["numero"]):
            falhas.append(
                f"numero: mostrando {atual!r} na tela, esperado {ind['numero']!r} "
                "(o SAPL deve ter sugerido outro numero depois do preenchimento - confira antes de salvar)"
            )

    return falhas, notas


def caminho_do_pdf(ind: dict) -> Path:
    """O PDF fatiado que voce anexa no campo "Texto original"."""
    from .config import PDFS_DIR

    return PDFS_DIR / f"{ind['numero']}-{ind['ano']}.pdf"
