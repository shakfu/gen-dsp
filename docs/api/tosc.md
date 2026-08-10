# TouchOSC

Generates a TouchOSC control surface from a `Manifest`, plus OSC receiver glue
for the Pd and SuperCollider backends. Layout generation requires py2tosc
(`pip install gen-dsp[tosc]`); the address and receiver layers do not.

## Addresses

::: gen_dsp.tosc.addresses
    options:
      members:
        - OscParam
        - osc_slug
        - osc_namespace
        - osc_params
        - default_prefix

## Surface

::: gen_dsp.tosc.surface
    options:
      members:
        - build_surface
        - write_surface

## Receivers

::: gen_dsp.tosc.receivers
    options:
      members:
        - generate_pd_receiver
        - generate_sc_receiver
        - receiver_for_platform

## Emit

::: gen_dsp.tosc.emit
    options:
      members:
        - emit
        - ToscOptions
        - ToscResult
