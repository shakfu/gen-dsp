# Architecture

A visual overview of how gen-dsp turns a gen~ export (or a Python/JSON graph) into a buildable plugin project. For the prose version and conventions, see the project's `CLAUDE.md`; for the library API, see the [Core API guide](api/core-guide.md).

## Pipeline data flow

Two front ends feed a single, front-end-agnostic intermediate representation (the `Manifest`), which every platform backend consumes. The gen~ path is zero-dependency; the graph path requires pydantic.

```mermaid
flowchart TD
    subgraph gen["gen~ export path (zero-dependency)"]
        E[gen~ export dir] --> P["core/parser.py"]
        P --> EI[ExportInfo]
        EI --> MB["manifest_from_export_info()"]
    end

    subgraph graph["graph frontend path (requires pydantic)"]
        G["Graph (Python / JSON)"] --> CO["graph/compile.py"]
        CO --> CPP["standalone C++"]
        CPP --> AD["graph/adapter.py"]
    end

    MB --> MAN[["Manifest IR<br/>(I/O, params, buffers)"]]
    AD --> MAN

    MAN --> PG["core/project.py<br/>ProjectGenerator"]
    PG --> PROJ["project dir<br/>(templates + manifest.json + .gen-dsp.json)"]
    PROJ --> BLD["core/builder.py<br/>Builder"]
    BLD --> PB["Platform.build()"]
    PB --> OUT([built plugin / firmware])
```

## CLI orchestration

`cli.py` wires the pipeline into subcommands. The `graph` subcommands are only available when the `[graph]` extra is installed.

```mermaid
flowchart LR
    CLI["cli.py"]
    CLI --> INIT["init<br/>(generate project)"]
    CLI --> BUILD["build<br/>(compile)"]
    CLI --> DETECT["detect<br/>(analyze export)"]
    CLI --> MANI["manifest<br/>(emit JSON IR)"]
    CLI --> LIST["list<br/>(platforms / boards)"]
    CLI --> CACHE["cache<br/>(show / prune SDKs)"]
    CLI --> GRP["graph: compile / validate / viz / simulate"]

    INIT --> PG["ProjectGenerator"]
    BUILD --> BL["Builder"]
    GRP -. requires pydantic .-> GP["gen_dsp.graph"]
```

## Platform registry

`platforms/__init__.py` holds `PLATFORM_REGISTRY`, mapping a string key to a `Platform` subclass. Adding a platform is a single-module change plus a registry entry. Backends group by build system:

```mermaid
flowchart TD
    REG[["PLATFORM_REGISTRY"]]

    REG --> CM["CMake + FetchContent"]
    REG --> CMX["CMake (Xcode)"]
    REG --> MK["Make"]
    REG --> EM["Make (emcc)"]

    CM --> CM1["au · clap · vst3 · lv2 · sc · max"]
    CMX --> CMX1["auv3"]
    MK --> MK1["pd · chuck · vcvrack · daisy · circle · standalone · csound"]
    EM --> EM1["webaudio"]
```

Each `Platform` implements `generate_project()`, `build()`, `clean()`, `find_output()`, and `get_build_instructions()`. SDKs for CMake/FetchContent and several Make backends are auto-downloaded into a shared cache.

## Header isolation pattern

Generated projects keep host-API code and genlib code in separate translation units that never include each other's headers. They communicate only through a small C interface (`_ext*.h`) over an opaque `GenState*` pointer, so the genlib sources compile without the host SDK and vice versa.

```mermaid
flowchart LR
    API["host-API .cpp<br/>(CLAP / VST3 / ... headers only)"]
    H["_ext*.h<br/>C interface · opaque GenState*"]
    EXT["_ext*.cpp<br/>(genlib headers only)"]

    API -->|"calls"| H
    H -->|"implemented by"| EXT
```
