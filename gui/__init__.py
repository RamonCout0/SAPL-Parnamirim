"""Interface grafica do SAPL-Parnamirim.

Tkinter puro (vem junto com o Python, nao acrescenta dependencia nenhuma) +
Pillow, que ja era usado para renderizar as paginas escaneadas.

A interface NAO reimplementa nada: ela chama o mesmo `src/pipeline.py` e o
mesmo `src/sapl.py` que os scripts de terminal usam. Qualquer regra corrigida
vale para os dois caminhos na mesma hora.
"""
