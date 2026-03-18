# Graph Adapter

Bridges dsp-graph compiled C++ to gen-dsp platform backends. Generates `_ext_{platform}.cpp` adapters, manifests, and simplified build files.

::: gen_dsp.graph.adapter
    options:
      members:
        - generate_adapter_cpp
        - generate_manifest_obj
        - generate_manifest
        - compile_for_gen_dsp
        - generate_graph_build_file
        - SUPPORTED_PLATFORMS
