"""Diagnostico: extrai o texto, acha os inicios e mostra como o PDF ficou fatiado.

Rode isso ANTES do pipeline completo, sempre que trocar o PDF de entrada.
Ele responde: todas as indicacoes foram encontradas? algum bloco ficou torto?

    python scripts\\00_diagnostico.py "caminho\\do.pdf" 2023
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from src.config import MARKDOWN_DIR, OUTPUT_DIR, garantir_dirs
from src.detect import (
    auditar,
    classificar_paginas,
    inferir_numeros,
    montar_blocos,
)
from src.textlayer import extrair_paginas, pagina_para_markdown


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    pdf = Path(sys.argv[1])
    ano = int(sys.argv[2]) if len(sys.argv) > 2 else 2023
    if not pdf.exists():
        print(f"ERRO: nao achei o PDF: {pdf}")
        return 1

    garantir_dirs()
    print(f"Lendo {pdf.name} ...")
    paginas = extrair_paginas(str(pdf))
    print(f"{len(paginas)} paginas extraidas\n")

    # Cache do texto: evita reprocessar o PDF nas etapas seguintes.
    (OUTPUT_DIR / "paginas.json").write_text(
        json.dumps(
            [{"numero": p.numero, "texto": p.texto} for p in paginas],
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    md = MARKDOWN_DIR / "_documento_completo.md"
    md.write_text(
        f"# {pdf.stem}\n\n" + "\n".join(pagina_para_markdown(p) for p in paginas),
        encoding="utf-8",
    )
    print(f"Markdown completo -> {md}")

    inicios, citacoes = classificar_paginas(paginas)
    inicios = inferir_numeros(inicios, ano)
    blocos = auditar(montar_blocos(inicios, len(paginas), ano))

    sem_cabecalho = [i for i in inicios if not i.tem_cabecalho]
    print(f"\n{len(inicios)} inicios de indicacao detectados")
    print(f"  {len(inicios) - len(sem_cabecalho)} pelo cabecalho com numero")
    print(f"  {len(sem_cabecalho)} apenas pela estrutura (cabecalho ilegivel)")

    print(f"\n{'-'*78}")
    print(f"{'INDICACAO':>12} | {'PAGINAS':>9} | {'PGS':>3} | AVISOS")
    print(f"{'-'*78}")
    for b in blocos:
        marca = "!!" if b.avisos else "  "
        print(
            f"{marca}{b.identificador:>10} | {b.faixa:>9} | {b.qtd_paginas:>3} | "
            f"{'; '.join(b.avisos)}"
        )

    if citacoes:
        print(f"\nNumeros ignorados, que NAO abrem indicacao ({len(citacoes)}):")
        for c in citacoes:
            print(f"  pg {c['pagina']:>4} -> {c['numero']}/{c['ano']:<5} [{c['motivo']}]")

    problemas = [b for b in blocos if b.avisos]
    print(f"\n{'='*78}")
    print(f"RESUMO: {len(blocos)} indicacoes, {len(problemas)} com aviso")
    total_pgs = sum(b.qtd_paginas for b in blocos)
    print(f"Paginas cobertas: {total_pgs} de {len(paginas)}")
    dist: dict[int, int] = {}
    for b in blocos:
        dist[b.qtd_paginas] = dist.get(b.qtd_paginas, 0) + 1
    print(f"Distribuicao de paginas por indicacao: {dict(sorted(dist.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
