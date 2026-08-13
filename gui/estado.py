"""O que a interface precisa lembrar entre uma tela e outra (e entre sessoes).

Ano e data de apresentacao sao digitados uma vez e usados nas quatro telas.
Ficam gravados em config/interface.json para nao ter de redigitar toda vez
que o programa abre - e o tipo de coisa que muda uma vez por lote, nao a
cada uso.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date

from src.config import CONFIG_DIR, OUTPUT_DIR

ARQUIVO = CONFIG_DIR / "interface.json"


@dataclass
class Estado:
    ano: int = 2023
    usar_ollama: bool = False
    usar_force_pdfs: bool = False
    # NAO existe data aqui. A data de apresentacao e de cada indicacao, lida do
    # documento dela (ver src/datas.py) - guardar uma data "do lote" foi um
    # erro de modelagem: num PDF real de 196 indicacoes ha 48 datas
    # diferentes, entao uma data unica cadastraria quase todas errado.

    @classmethod
    def carregar(cls) -> "Estado":
        if not ARQUIVO.exists():
            return cls()
        try:
            dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Preferencia corrompida nao pode impedir o programa de abrir:
            # e conveniencia, nao dado de trabalho.
            return cls()
        conhecidos = {c for c in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in dados.items() if k in conhecidos})

    def salvar(self) -> None:
        try:
            ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
            ARQUIVO.write_text(
                json.dumps(asdict(self), ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        except OSError:
            pass  # nao vale travar a interface por causa de preferencia

    @property
    def indicacoes_json(self):
        return OUTPUT_DIR / "indicacoes.json"


def data_valida(texto: str) -> bool:
    """dd/mm/aaaa que existe de verdade (rejeita 31/02/2023)."""
    partes = texto.strip().split("/")
    if len(partes) != 3 or not all(p.isdigit() for p in partes):
        return False
    dia, mes, ano = (int(p) for p in partes)
    if not (1000 <= ano <= 9999):
        return False
    try:
        date(ano, mes, dia)
    except ValueError:
        return False
    return True
