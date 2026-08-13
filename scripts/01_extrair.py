"""Pipeline completo: tudo que estiver em input/ -> PDFs separados + planilha
pronta para o SAPL.

    python scripts\\01_extrair.py                    processa tudo em input\\
    python scripts\\01_extrair.py --ano 2023          ano padrao (se o nome do arquivo
                                                       nao terminar em "@AAAA.pdf")
    python scripts\\01_extrair.py "caminho\\do.pdf"    processa so esse arquivo
    python scripts\\01_extrair.py --sem-ollama         rapido, so regex
    python scripts\\01_extrair.py --sem-pdfs           nao refatia os PDFs
     python scripts\\01_extrair.py --force-pdfs        força recriar os PDFs mesmo que tenham sido gerados antes

Coloque os PDFs em input\\ e rode sem argumento nenhum - e o jeito normal de
usar. A cada execucao, o output e reconstruido do zero a partir do que estiver
em input\\ naquele momento: se voce tirar um PDF de la, as indicacoes dele
somem do output na proxima rodada. As correcoes que voce fez no glossario nao
se perdem - isso e preservado entre execucoes.

Saidas em output/:
    pdfs/NNN-AAAA.pdf          um arquivo por indicacao, pronto para anexar
    indicacoes.csv             uma linha por indicacao, com os IDs do SAPL
    indicacoes.json            o mesmo, com toda a rastreabilidade
    markdown/NNN-AAAA.md       leitura humana de cada indicacao
    revisao_manual/            PNG das paginas duvidosas + glossario.csv
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from src.config import INPUT_DIR
from src.pipeline import GLOSSARIO, processar_pasta


def _posicionais(args: list[str]) -> list[str]:
    """Argumentos que nao sao flag nem o VALOR de uma flag.

    "--ano" consome o proximo argumento (o numero do ano) - sem pular esse
    valor, "python 01_extrair.py --ano 2021" tratava "2021" como se fosse o
    caminho da pasta de entrada, achava "nenhum PDF" e zerava o output de
    verdade. Testado e corrigido.
    """
    flags_com_valor = {"--ano"}
    resultado = []
    pular = False
    for a in args:
        if pular:
            pular = False
            continue
        if a in flags_com_valor:
            pular = True
            continue
        if not a.startswith("--"):
            resultado.append(a)
    return resultado


def main() -> int:
    args = sys.argv[1:]

    origem = _posicionais(args)[:1] or [INPUT_DIR]
    origem = origem[0]

    ano = 2023
    ano_explicito = "--ano" in args
    if ano_explicito:
        ano = int(args[args.index("--ano") + 1])

    try:
        force_pdfs = "--force-pdfs" in args
        indicacoes = processar_pasta(
            origem,
            ano_padrao=ano,
            ano_forcado=ano_explicito,
            usar_ollama="--sem-ollama" not in args,
            gerar_pdfs="--sem-pdfs" not in args,
            force_pdfs=force_pdfs,
        )
    except FileNotFoundError as e:
        print(f"\nERRO: {e}")
        return 1
    if not indicacoes:
        # Pasta vazia e um estado valido (nao um erro): o output ja foi
        # zerado dentro de processar_pasta. So avisa e sai.
        print(f"\nOutput zerado - nada em {INPUT_DIR} agora.")
        print("Coloque um PDF la e rode de novo.")
        return 1

    prontas = [i for i in indicacoes if i.status == "pronto"]
    revisao = [i for i in indicacoes if i.status == "revisao"]

    print(f"\n{'='*78}")
    print(f"{len(indicacoes)} indicacoes | {len(prontas)} prontas | {len(revisao)} para revisar")
    print(f"{'='*78}")

    if revisao:
        print("\nPARA REVISAR:")
        for i in revisao:
            print(f"  {i.identificador:>9}  pgs {i.pagina_inicial}-{i.pagina_final}  "
                  f"{' | '.join(i.motivos)}")
        print(f"\n  Abra o formulario de revisao no navegador:")
        print(f"    .venv\\Scripts\\python scripts\\03_revisar.py")
        print(f"  (ou edite direto: {GLOSSARIO})")
        print("\n  Depois de revisar, rode este script de novo para incorporar.")

    autores: dict[str, int] = {}
    for i in prontas:
        autores[i.autor_nome_sapl] = autores.get(i.autor_nome_sapl, 0) + 1
    if autores:
        print("\nAutores nas indicacoes prontas:")
        for nome, qtd in sorted(autores.items(), key=lambda x: -x[1]):
            print(f"  {qtd:>3}  {nome}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
