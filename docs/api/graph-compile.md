# Graph Compiler

Compiles a `Graph` to standalone C++ code, or C99 with `lang="c"` (no genlib dependency). `compile_graph_header()` returns the matching C header, and `compile_graph_to_file(..., lang="c")` writes `<name>.c` and `<name>.h`. The output compiles cleanly under `-Wall -Wextra -Wshadow -Werror`. IDs `self`, `ins`, `outs`, `n`, `i` and `sr` are reserved (a SampleRate node may be `sr`), as are IDs starting with `_` unless they end in `_<digits>`.

::: gen_dsp.graph.compile
