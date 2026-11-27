"""The business rules: everything RightPrice decides about fabrics, prices and negotiations, between the costing
engine (engine.py, masters.py) and the web requests (server.py). The rules read and write only through store.py.

One module per area; a module refers to another by its name (common.get_masters, tracker.nego_summary ...)."""
