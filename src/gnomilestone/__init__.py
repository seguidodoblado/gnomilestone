__version__ = "0.3.0"

import os as _os

# IBus 1.5.29 (Ubuntu 24.04) con GTK4 no confirma la tecla muerta: la tilde queda flotando como
# pre-edición («Type 'h' is not supported») hasta pasar a otro campo o borrar hacia atrás. El
# método de entrada integrado de GTK compone bien las teclas muertas, así que se usa ese. Tiene que
# fijarse antes de que GTK arranque, por eso va aquí y no en app.py.
if _os.environ.get("GTK_IM_MODULE") == "ibus":
    _os.environ["GTK_IM_MODULE"] = "simple"
