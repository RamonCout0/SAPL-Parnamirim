"""Abre o formulario do SAPL com os campos ja preenchidos, um por vez.

O script preenche e PARA. Ele nunca salva. Voce faz as duas coisas que ficaram
para a mao - anexar o PDF de output/pdfs/ e escrever a data de apresentacao -
confere a tela e clica em salvar.

O campo "Autor" do SAPL costuma so liberar as opcoes DEPOIS que a data e
preenchida (filtra por quem estava no mandato naquela data). Como a data e
sempre manual, isso aparece como um aviso "atenção: autor não pré-
selecionado", nao como falha - depois de preencher a data, so selecionar o
autor certo manualmente (o aviso ja diz qual).

    python scripts\\02_preencher_sapl.py --inspecionar     lista os campos reais
    python scripts\\02_preencher_sapl.py                   percorre as prontas
    python scripts\\02_preencher_sapl.py --numero 300      so a 300
    python scripts\\02_preencher_sapl.py --de 300 --ate 290
    python scripts\\02_preencher_sapl.py --ano 2022        so o lote de 2022

Sem "--ano", o script PERGUNTA qual ano trabalhar - mas so quando ha mais de
um ano misturado nas prontas (um lote so nao incomoda com a pergunta).

Sem "--numero"/"--de"/"--ate", o script tambem PERGUNTA de qual numero
comecar (ENTER para comecar do topo) - assim, se parou na 256 numa sessao
anterior, nao precisa apertar ENTER em tudo de novo desde a 300, so digita
256.

Se a janela travar ou fechar no meio (trocar de tela, minimizar por muito
tempo etc.), o script nao derruba a sessao inteira: avisa o erro e pergunta
se voce quer tentar de novo, pular aquela indicacao, ou parar por ali - da
para continuar depois informando o numero onde parou.

O navegador e Firefox (instancia propria do Playwright, nao a janela que voce
ja tem aberta - Playwright so conecta em janelas ja abertas de navegadores
baseados em Chrome). Primeira execucao: a janela abre na tela de login do SAPL
e espera VOCE entrar. A sessao fica salva no perfil do projeto
(.perfil_navegador\\), entao nas proximas vezes ja abre logado. O script nunca
digita senha - quem faz o login e voce.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from src.config import OUTPUT_DIR
# A logica de preencher vive em src/sapl.py, compartilhada com a interface
# grafica - as duas telas preenchem igual porque e o mesmo codigo.
from src.sapl import (
    PERFIL,
    achar,
    carregar_form,
    descobrir_rotas,
    listar_campos,
    preencher,
)
from src.sapl import pagina_valida as _pagina_valida


def inspecionar(pagina) -> None:
    campos = listar_campos(pagina)
    print(f"\n{len(campos)} campos na pagina:\n")
    print(f"{'TAG':<9} {'TIPO':<10} {'ID':<30} {'NAME':<28} ROTULO")
    for c in campos:
        if c["tipo"] in ("hidden", "csrfmiddlewaretoken"):
            continue
        rotulo = " ".join(c["rotulo"].split())[:40]
        print(f"{c['tag']:<9} {c['tipo']:<10} {c['id']:<30} {c['name']:<28} {rotulo}")
    print("\nAjuste config\\sapl_form.json com os ids/names que aparecem acima.")



def _pedir_ano(itens: list[dict], args: list[str]) -> list[dict]:
    """Filtra por ano. "--ano AAAA" na linha de comando decide direto; sem
    isso, so pergunta se houver mais de um ano misturado entre as prontas -
    nao incomoda quando o lote e so de um ano."""
    if "--ano" in args:
        ano = int(args[args.index("--ano") + 1])
        return [i for i in itens if i["ano"] == ano]

    anos = sorted({i["ano"] for i in itens}, reverse=True)
    if len(anos) <= 1:
        return itens

    print("\nMais de um ano entre as prontas:")
    for a in anos:
        qtd = sum(1 for i in itens if i["ano"] == a)
        print(f"  {a}: {qtd}")
    resposta = input("Qual ano? (ENTER para todos): ").strip()
    if not resposta:
        return itens
    try:
        ano = int(resposta)
    except ValueError:
        print(f"  '{resposta}' não é um ano válido - mostrando todos.")
        return itens

    filtrado = [i for i in itens if i["ano"] == ano]
    if not filtrado:
        print(f"  nenhuma pronta de {ano} - mostrando todos.")
        return itens
    return filtrado


def _pedir_numero_inicial(prontas: list[dict]) -> list[dict]:
    """Pergunta de onde comecar, para nao precisar apertar ENTER desde o topo
    toda vez que a sessao para no meio. So pergunta no uso interativo (sem
    --numero/--de/--ate, que ja resolvem isso via linha de comando)."""
    numeros = [i["numero"] for i in prontas]
    print(f"\n{len(prontas)} prontas: da {numeros[0]} ate {numeros[-1]}.")
    resposta = input(
        "Começar de qual número? (ENTER para começar do topo): "
    ).strip()
    if not resposta:
        return prontas
    try:
        inicio = int(resposta)
    except ValueError:
        print(f"  '{resposta}' não é um número - começando do topo mesmo.")
        return prontas

    cortado = [i for i in prontas if i["numero"] <= inicio]
    if not cortado:
        print(f"  nenhuma pronta com número <= {inicio} - começando do topo mesmo.")
        return prontas
    print(f"  começando em {cortado[0]['numero']}/{cortado[0]['ano']}.")
    return cortado


def main() -> int:
    args = sys.argv[1:]
    form = carregar_form()
    base = form["base_url"].rstrip("/")
    url_form = base + form["caminho_formulario"]

    dados = json.loads((OUTPUT_DIR / "indicacoes.json").read_text(encoding="utf-8"))
    prontas = [i for i in dados["indicacoes"] if i["status"] == "pronto"]
    so_inspecionar = "--inspecionar" in args

    if prontas and not so_inspecionar:
        prontas = _pedir_ano(prontas, args)

    filtro_por_cli = "--numero" in args or "--de" in args or "--ate" in args
    if "--numero" in args:
        alvo = int(args[args.index("--numero") + 1])
        prontas = [i for i in prontas if i["numero"] == alvo]
    if "--de" in args:
        de = int(args[args.index("--de") + 1])
        prontas = [i for i in prontas if i["numero"] <= de]
    if "--ate" in args:
        ate = int(args[args.index("--ate") + 1])
        prontas = [i for i in prontas if i["numero"] >= ate]

    if not prontas and not so_inspecionar:
        print("Nenhuma indicacao com status 'pronto'. Rode 01_extrair.py primeiro.")
        return 1

    if prontas and not so_inspecionar and not filtro_por_cli:
        prontas = _pedir_numero_inicial(prontas)

    PERFIL.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        # Firefox, nao Chromium: e o navegador que o usuario ja usa no dia a
        # dia, entao a tela de preenchimento fica com a cara familiar. Nao da
        # para conectar na janela de Firefox que a pessoa ja tem aberta -
        # Playwright so oferece isso (connect_over_cdp) para navegadores
        # baseados em Chrome. Este Firefox e uma instancia propria do
        # Playwright, com perfil salvo em .perfil_navegador/: o login e feito
        # uma vez e fica gravado para as proximas execucoes.
        nav = p.firefox.launch_persistent_context(
            user_data_dir=str(PERFIL),
            headless=False,
            viewport={"width": 1500, "height": 950},
        )
        pagina = nav.pages[0] if nav.pages else nav.new_page()

        pagina.goto(url_form, wait_until="domcontentloaded")
        if "login" in pagina.url.lower():
            print(f"\nFaca o login no SAPL na janela que abriu ({pagina.url}).")
            print("Eu nao digito senha - quando terminar, aperte ENTER aqui.")
            input()
            pagina.goto(url_form, wait_until="domcontentloaded")

        if so_inspecionar:
            print(f"\nPagina: {pagina.url}\nTitulo: {pagina.title()!r}")
            inspecionar(pagina)
            print("\nRotas de materia visiveis com o seu login:")
            for rota in descobrir_rotas(pagina, base) or ["  (nenhuma encontrada)"]:
                print(f"  {rota}")
            input("\nENTER para fechar. ")
            nav.close()
            return 0

        # O formulario tem de ter o campo ementa. Se nao tiver, o caminho no
        # config esta errado (ou o usuario nao tem permissao de cadastro).
        if achar(pagina, form["campos"]["ementa"]) is None:
            print(f"\nO formulario nao apareceu em {url_form}")
            print(f"  (a pagina respondeu como: {pagina.title()!r})")
            print("\nRotas de materia visiveis com o seu login:")
            for rota in descobrir_rotas(pagina, base) or ["  (nenhuma encontrada)"]:
                print(f"  {rota}")
            print("\nAjuste 'caminho_formulario' em config\\sapl_form.json e rode de novo.")
            input("\nENTER para fechar. ")
            nav.close()
            return 1

        print(f"\n{len(prontas)} indicacoes para cadastrar.")
        print("Para cada uma: eu preencho, voce anexa o PDF, poe a data e salva.\n")

        n = 0
        parou_em: dict | None = None
        while n < len(prontas):
            ind = prontas[n]
            n += 1
            try:
                pagina = _pagina_valida(nav, pagina)
                pagina.goto(url_form, wait_until="domcontentloaded")
                falhas, notas = preencher(pagina, form, ind)
            except PlaywrightError as e:
                # A janela pode ter sido fechada, travado, ou ficado tempo
                # demais em segundo plano - isto evita que a sessao inteira
                # caia por causa de UMA indicacao. "numero onde parou" fica
                # registrado para retomar depois com o prompt inicial.
                print(f"{'-'*74}")
                print(f"[{n}/{len(prontas)}] Indicação {ind['numero']}/{ind['ano']} - ERRO NO NAVEGADOR")
                print(f"  {type(e).__name__}: {str(e).splitlines()[0]}")
                resp = input(
                    "  [t] tentar de novo   [p] pular esta   [s] parar aqui: "
                ).strip().lower()
                if resp == "t":
                    n -= 1  # repete a mesma indicacao na proxima volta
                    continue
                if resp == "p":
                    continue
                parou_em = ind
                break

            print(f"{'-'*74}")
            print(f"[{n}/{len(prontas)}] Indicação {ind['numero']}/{ind['ano']}")
            print(f"  autor : {ind['autor_nome_sapl']} (id {ind['autor_id']})")
            print(f"  ementa: {ind['ementa'][:150]}...")
            print(f"  anexar: output\\pdfs\\{ind['numero']}-{ind['ano']}.pdf")
            print("  falta : data de apresentação + texto original")
            if notas:
                for nota in notas:
                    print(f"  atenção: {nota}")
            if falhas:
                print("  FALHAS AO PREENCHER:")
                for f in falhas:
                    print(f"    - {f}")
                print("    (rode --inspecionar e corrija config\\sapl_form.json)")

            resposta = input("  ENTER para a proxima, 's' para sair: ").strip().lower()
            if resposta == "s":
                parou_em = prontas[n] if n < len(prontas) else None
                break

        if parou_em:
            print(f"\nParou em {parou_em['numero']}/{parou_em['ano']}. Para continuar dali:")
            print(f"  .venv\\Scripts\\python scripts\\02_preencher_sapl.py")
            print(f"  (e digite {parou_em['numero']} quando ele perguntar de onde começar)")

        print("\nFim. A janela fica aberta; feche quando quiser.")
        input("ENTER para encerrar o navegador. ")
        nav.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
