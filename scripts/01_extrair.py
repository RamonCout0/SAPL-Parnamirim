"""Pipeline completo: PDF unico -> PDFs separados + planilha pronta para o SAPL.

    python scripts\\01_extrair.py "caminho\\do.pdf"
    python scripts\\01_extrair.py "caminho\\do.pdf" --ano 2023
    python scripts\\01_extrair.py "caminho\\do.pdf" --sem-ollama   (rapido, so regex)
    python scripts\\01_extrair.py "caminho\\do.pdf" --sem-pdfs     (nao refatia)

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

from src.pipeline import GLOSSARIO, processar


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2

    pdf = Path(args[0])
    if not pdf.exists():
        print(f"ERRO: nao achei o PDF: {pdf}")
        return 1

    ano = 2023
    if "--ano" in args:
        ano = int(args[args.index("--ano") + 1])

    indicacoes = processar(
        str(pdf),
        ano=ano,
        usar_ollama="--sem-ollama" not in args,
        gerar_pdfs="--sem-pdfs" not in args,
    )

    prontas = [i for i in indicacoes if i.status == "pronto"]
    revisao = [i for i in indicacoes if i.status == "revisao"]

    print(f"\n{'='*78}")
    print(f"{len(indicacoes)} indicacoes | {len(prontas)} prontas | {len(revisao)} para revisar")
    print(f"{'='*78}")

    if revisao:
        print("\nPARA REVISAR (confira o PNG e preencha o glossario):")
        for i in revisao:
            print(f"  {i.identificador:>9}  pgs {i.pagina_inicial}-{i.pagina_final}  "
                  f"{' | '.join(i.motivos)}")
        print(f"\n  glossario: {GLOSSARIO}")
        print("  imagens  : output\\revisao_manual\\imagens")
        print("  IDs autor: output\\revisao_manual\\IDS_DE_AUTOR.md")
        print("\n  Depois de preencher, rode este script de novo para incorporar.")

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
