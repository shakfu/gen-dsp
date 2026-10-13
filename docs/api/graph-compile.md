# Graph Compiler

Compiles a `Graph` to standalone C++ code, or C99 with `lang="c"` (no genlib dependency). `compile_graph_header()` returns the matching C header, and `compile_graph_to_file(..., lang="c")` writes `<name>.c` and `<name>.h`. The output compiles cleanly under `-Wall -Wextra -Werror`.

::: gen_dsp.graph.compile
