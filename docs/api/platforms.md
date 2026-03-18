# Platforms

Platform base class, registry, and helper functions. Each platform implements `generate_project()`, `build()`, `clean()`, `find_output()`.

::: gen_dsp.platforms.base

::: gen_dsp.platforms.cmake_platform

::: gen_dsp.platforms
    options:
      members:
        - PLATFORM_REGISTRY
        - get_platform
        - get_platform_class
        - list_platforms
        - list_cmake_platforms
        - is_valid_platform
