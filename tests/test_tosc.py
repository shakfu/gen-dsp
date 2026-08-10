"""Tests for TouchOSC surface generation and OSC receiver glue.

The address and receiver layers are dependency-free and always tested. The
layout layer needs py2tosc and is skipped without it.
"""

import json
import re

import pytest

from gen_dsp.cli import main
from gen_dsp.core.manifest import Manifest, ParamInfo
from gen_dsp.tosc.addresses import (
    CC_LIMIT,
    osc_namespace,
    osc_params,
    osc_slug,
)
from gen_dsp.tosc.receivers import (
    generate_pd_receiver,
    generate_sc_receiver,
    receiver_for_platform,
)


def make_manifest(params=None, num_inputs=2, num_outputs=2, gen_name="reverb"):
    """Build a manifest with the given parameters."""
    if params is None:
        params = [
            ParamInfo(0, "bandwidth", True, 0.0, 1.0, 0.5),
            ParamInfo(1, "roomsize", True, 0.1, 300.0, 75.0),
        ]
    return Manifest(
        gen_name=gen_name,
        num_inputs=num_inputs,
        num_outputs=num_outputs,
        params=params,
    )


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("bandwidth", "bandwidth"),
        ("room size", "roomSize"),
        ("c/m ratio", "cMRatio"),
        ("Dry/Wet", "dryWet"),
        ("freq_2", "freq2"),
        ("MIX", "mix"),
    ],
)
def test_osc_slug(raw, expected):
    assert osc_slug(raw) == expected


def test_osc_slug_falls_back_when_nothing_survives():
    assert osc_slug("???", "param3") == "param3"


def test_osc_slug_drops_reserved_characters():
    # OSC reserves these; none may appear in a generated address.
    slug = osc_slug("a#b*c,d?e[f]g{h}i j")
    assert not set(slug) & set("#*,?[]{} /")


def test_osc_namespace_keeps_segments():
    assert osc_namespace("Synth/Bank 1") == "synth/bank1"


def test_osc_namespace_falls_back_when_empty():
    assert osc_namespace("///", "surface") == "surface"


def test_osc_params_addresses_and_cc():
    params = osc_params(make_manifest())
    assert [p.address for p in params] == [
        "/reverb/bandwidth",
        "/reverb/roomsize",
    ]
    assert [p.cc for p in params] == [0, 1]


def test_osc_params_explicit_prefix():
    params = osc_params(make_manifest(), prefix="My Rig/Voice 1")
    assert params[0].address == "/myRig/voice1/bandwidth"


def test_osc_params_empty_prefix_addresses_at_root():
    params = osc_params(make_manifest(), prefix="")
    assert params[0].address == "/bandwidth"


def test_osc_params_disambiguates_colliding_slugs():
    manifest = make_manifest(
        params=[
            ParamInfo(0, "cutoff hz", True, 0.0, 1.0, 0.0),
            ParamInfo(1, "cutoff-hz", True, 0.0, 1.0, 0.0),
        ]
    )
    slugs = [p.slug for p in osc_params(manifest)]
    assert slugs == ["cutoffHz", "cutoffHz_2"]
    assert len(set(p.address for p in osc_params(manifest))) == 2


def test_osc_params_beyond_cc_limit_have_no_cc():
    params = [ParamInfo(i, f"p{i}", True, 0.0, 1.0, 0.0) for i in range(CC_LIMIT + 2)]
    mapped = osc_params(make_manifest(params=params))
    assert mapped[CC_LIMIT - 1].cc == CC_LIMIT - 1
    assert mapped[CC_LIMIT].cc is None
    assert mapped[CC_LIMIT + 1].cc is None


def test_normalized_default_maps_range_onto_fader():
    manifest = make_manifest(
        params=[ParamInfo(0, "roomsize", True, 100.0, 300.0, 150.0)]
    )
    assert osc_params(manifest)[0].normalized_default == pytest.approx(0.25)


def test_normalized_default_of_degenerate_range_is_zero():
    manifest = make_manifest(params=[ParamInfo(0, "flag", False, 0.0, 0.0, 0.0)])
    assert osc_params(manifest)[0].normalized_default == 0.0


def test_normalized_default_is_clamped():
    # gen~ initial values can sit outside the declared range.
    manifest = make_manifest(params=[ParamInfo(0, "gain", True, 0.0, 1.0, 4.0)])
    assert osc_params(manifest)[0].normalized_default == 1.0


# ---------------------------------------------------------------------------
# Pure Data receiver
# ---------------------------------------------------------------------------


def test_pd_receiver_structure():
    patch = generate_pd_receiver(make_manifest(), lib_name="reverb", port=9001)

    assert patch.startswith("#N canvas ")
    assert "netreceive -u -b 9001" in patch
    assert "oscparse" in patch
    assert "route reverb" in patch
    assert "route bandwidth roomsize" in patch
    assert "#X msg 20 250 bandwidth \\$1;" in patch
    assert "reverb~" in patch
    assert "adc~" in patch and "dac~" in patch


def test_pd_receiver_connection_indices_are_in_range():
    patch = generate_pd_receiver(make_manifest())
    elements = len(re.findall(r"^#X (?:obj|msg|text) ", patch, re.MULTILINE))
    connections = re.findall(r"^#X connect (\d+) (\d+) (\d+) (\d+);$", patch, re.M)
    assert connections
    for src, _, dst, _ in connections:
        assert int(src) < elements
        assert int(dst) < elements


def test_pd_receiver_uses_the_prefix_it_is_given():
    patch = generate_pd_receiver(make_manifest(), prefix="rig/voice1")
    assert "route rig;" in patch
    assert "route voice1;" in patch


def test_pd_receiver_normalizes_a_prefix_before_routing():
    # A raw "voice 1" would become a route over two atoms and match nothing.
    patch = generate_pd_receiver(make_manifest(), prefix="Rig/voice 1")
    assert "route rig;" in patch
    assert "route voice1;" in patch
    assert osc_params(make_manifest(), prefix="Rig/voice 1")[0].address.startswith(
        "/rig/voice1/"
    )


def test_pd_receiver_routes_on_the_slug_and_sends_the_host_name():
    manifest = make_manifest(params=[ParamInfo(0, "cutoff-hz", True, 0.0, 1.0, 0.0)])
    patch = generate_pd_receiver(manifest, lib_name="filter_")
    # The address's last segment is the slug, but the message the external
    # answers to is its own name.
    assert "route cutoffHz;" in patch
    assert "cutoff-hz \\$1" in patch


def test_pd_receiver_skips_names_a_message_box_cannot_express():
    manifest = make_manifest(
        params=[
            ParamInfo(0, "bandwidth", True, 0.0, 1.0, 0.0),
            ParamInfo(1, "c/m ratio", True, 0.0, 1.0, 0.0),
        ]
    )
    patch = generate_pd_receiver(manifest)
    assert "route bandwidth;" in patch
    assert "not routed" in patch
    assert "c/m ratio" in patch


def test_pd_receiver_generator_has_no_adc():
    patch = generate_pd_receiver(make_manifest(num_inputs=0), lib_name="synth")
    assert "adc~" not in patch
    assert "dac~" in patch


def test_pd_receiver_rejects_bad_port():
    with pytest.raises(ValueError, match="port"):
        generate_pd_receiver(make_manifest(), port=0)
    with pytest.raises(ValueError, match="port"):
        generate_pd_receiver(make_manifest(), port=70000)


def test_pd_receiver_with_no_params_still_renders():
    patch = generate_pd_receiver(make_manifest(params=[]), lib_name="reverb")
    assert "reverb~" in patch
    assert "#X msg" not in patch


# ---------------------------------------------------------------------------
# SuperCollider receiver
# ---------------------------------------------------------------------------


def test_sc_receiver_structure():
    script = generate_sc_receiver(make_manifest(), lib_name="reverb")

    assert "SynthDef(\\reverb" in script
    assert "Reverb.ar(SoundIn.ar(0), SoundIn.ar(1), bandwidth, roomsize)" in script
    assert "OSCdef(\\reverb_bandwidth" in script
    assert "'/reverb/bandwidth'" in script
    assert "~reverb.set(\\bandwidth, msg[1])" in script


def test_sc_receiver_controls_carry_parameter_defaults():
    script = generate_sc_receiver(make_manifest(), lib_name="reverb")
    assert "bandwidth = 0.5" in script
    assert "roomsize = 75" in script


def test_sc_receiver_control_names_match_the_generated_class():
    from gen_dsp.platforms.supercollider import SuperColliderPlatform

    manifest = make_manifest(params=[ParamInfo(0, "c/m ratio", True, 0.0, 10.0, 1.0)])
    script = generate_sc_receiver(manifest, lib_name="fm")
    expected = SuperColliderPlatform._sanitize_sc_arg("c/m ratio")
    assert f"{expected} = 1" in script
    assert f"~fm.set(\\{expected}, msg[1])" in script


def test_sc_receiver_generator_takes_no_input():
    script = generate_sc_receiver(make_manifest(num_inputs=0), lib_name="synth")
    assert "SoundIn" not in script


def test_receiver_for_platform_covers_pd_and_sc_only():
    manifest = make_manifest()
    pd_name, pd_body = receiver_for_platform("pd", manifest, lib_name="reverb")
    sc_name, sc_body = receiver_for_platform("sc", manifest, lib_name="reverb")
    assert pd_name == "reverb_osc.pd"
    assert sc_name == "reverb_osc.scd"
    assert pd_body and sc_body
    assert receiver_for_platform("clap", manifest, lib_name="reverb") is None


# ---------------------------------------------------------------------------
# Behaviour when py2tosc is missing
# ---------------------------------------------------------------------------


def test_require_tosc_points_at_the_extra(monkeypatch):
    import gen_dsp.tosc as tosc

    monkeypatch.setattr(tosc, "_AVAILABLE", False)
    with pytest.raises(ImportError, match=r"gen-dsp\[tosc\]"):
        tosc._require_tosc()


def test_project_generation_reports_a_missing_py2tosc(
    monkeypatch, tmp_path, gigaverb_export
):
    import gen_dsp.tosc as tosc
    from gen_dsp.core.parser import GenExportParser
    from gen_dsp.core.project import ProjectConfig, ProjectGenerator
    from gen_dsp.errors import ProjectError

    monkeypatch.setattr(tosc, "_AVAILABLE", False)
    export_info = GenExportParser(gigaverb_export).parse()
    config = ProjectConfig(name="gigaverb", platform="pd", tosc=True)
    generator = ProjectGenerator(export_info, config)
    with pytest.raises(ProjectError, match=r"gen-dsp\[tosc\]"):
        generator.generate(tmp_path / "proj")


def test_receivers_do_not_import_py2tosc():
    # The receiver half must keep working in a bare install.
    import subprocess
    import sys

    script = (
        "import sys;"
        "sys.modules['py2tosc'] = None;"
        "import gen_dsp.tosc as t;"
        "assert t._AVAILABLE is False;"
        "from gen_dsp.core.manifest import Manifest, ParamInfo;"
        "m = Manifest(gen_name='r', num_inputs=1, num_outputs=1,"
        " params=[ParamInfo(0, 'gain', True, 0.0, 1.0, 0.5)]);"
        "assert 'route gain' in t.generate_pd_receiver(m);"
        "assert 'OSCdef' in t.generate_sc_receiver(m)"
    )
    subprocess.run([sys.executable, "-c", script], check=True)


# ---------------------------------------------------------------------------
# Surface (requires py2tosc)
# ---------------------------------------------------------------------------

py2tosc = pytest.importorskip("py2tosc")

from gen_dsp.errors import ValidationError  # noqa: E402
from gen_dsp.tosc.emit import ToscOptions, emit  # noqa: E402
from gen_dsp.tosc.surface import build_surface, write_surface  # noqa: E402


def find_faders(doc):
    """Return the document's faders, in document order."""
    return [c for c in doc.walk() if str(c.control_type) == "FADER"]


def test_build_surface_has_one_fader_per_parameter():
    doc = build_surface(make_manifest())
    assert len(find_faders(doc)) == 2


def test_build_surface_addresses_carry_the_parameter_range():
    doc = build_surface(make_manifest())
    by_name = {f.get("name"): f for f in find_faders(doc)}

    roomsize = by_name["roomsize"]
    osc_messages = [m for m in roomsize.messages if isinstance(m, py2tosc.OscMessage)]
    assert len(osc_messages) == 1
    argument = osc_messages[0].arguments[0]
    assert argument.scale_min == pytest.approx(0.1)
    assert argument.scale_max == pytest.approx(300.0)


def test_build_surface_faders_start_at_the_parameter_default():
    doc = build_surface(make_manifest())
    by_name = {f.get("name"): f for f in find_faders(doc)}
    x = [v for v in by_name["roomsize"].values if v.key == "x"][0]
    # 75 in [0.1, 300] -> just under a quarter of the way up.
    assert x.default == pytest.approx((75.0 - 0.1) / (300.0 - 0.1))


def test_build_surface_binds_midi_cc_by_parameter_index():
    doc = build_surface(make_manifest())
    midi = [
        m
        for f in find_faders(doc)
        for m in f.messages
        if isinstance(m, py2tosc.MidiMessage)
    ]
    assert len(midi) == 2


def test_build_surface_can_omit_midi():
    doc = build_surface(make_manifest(), midi=False)
    assert not [
        m
        for f in find_faders(doc)
        for m in f.messages
        if isinstance(m, py2tosc.MidiMessage)
    ]


def test_build_surface_can_omit_osc():
    doc = build_surface(make_manifest(), osc=False)
    assert not [
        m
        for f in find_faders(doc)
        for m in f.messages
        if isinstance(m, py2tosc.OscMessage)
    ]


def test_build_surface_captions_use_the_host_name():
    manifest = make_manifest(params=[ParamInfo(0, "c/m ratio", True, 0.0, 10.0, 1.0)])
    doc = build_surface(manifest)
    captions = [
        v.default
        for c in doc.walk()
        if str(c.get("name", "")).endswith("Caption")
        for v in c.values
        if v.key == "text"
    ]
    assert captions == ["c/m ratio"]


def test_build_surface_pages_long_parameter_lists():
    params = [ParamInfo(i, f"p{i}", True, 0.0, 1.0, 0.0) for i in range(30)]
    doc = build_surface(make_manifest(params=params), columns=4, rows=3)
    pagers = [c for c in doc.walk() if str(c.control_type) == "PAGER"]
    assert len(pagers) == 1
    assert len(pagers[0].children) == 3  # 30 params at 12 per page
    assert len(find_faders(doc)) == 30


def test_build_surface_rejects_a_manifest_with_no_parameters():
    with pytest.raises(ValidationError, match="no parameters"):
        build_surface(make_manifest(params=[]))


def test_emit_names_the_plugin_when_a_surface_cannot_be_built(tmp_path):
    with pytest.raises(ValidationError, match="'reverb'"):
        emit(make_manifest(params=[]), tmp_path, "reverb")


def test_project_generation_continues_without_a_surface(tmp_path, multitap_export):
    # multitap has buffers but no parameters. The project is still valid; only
    # the surface is impossible.
    from gen_dsp.core.parser import GenExportParser
    from gen_dsp.core.project import ProjectConfig, ProjectGenerator

    export_info = GenExportParser(multitap_export).parse()
    config = ProjectConfig(name="multitap", platform="pd", tosc=True)
    generator = ProjectGenerator(export_info, config)
    project = generator.generate(tmp_path / "proj")

    assert generator.tosc_result is None
    assert "no parameters" in generator.tosc_skipped
    # The project itself is complete -- including the gen~ export copied after
    # the point the surface is written.
    assert (project / "gen").is_dir()
    assert (project / "Makefile").is_file()
    assert not list(project.glob("*.tosc"))


def test_cli_warns_when_a_surface_cannot_be_built(tmp_path, multitap_export, capsys):
    rc = main(
        [
            str(multitap_export),
            "-n",
            "multitap",
            "-p",
            "pd",
            "--tosc",
            "--no-build",
            "-o",
            str(tmp_path / "proj"),
        ]
    )
    assert rc == 0
    assert "no TouchOSC surface" in capsys.readouterr().out


def test_build_surface_rejects_no_bindings():
    with pytest.raises(ValidationError, match="neither"):
        build_surface(make_manifest(), osc=False, midi=False)


def test_build_surface_rejects_degenerate_geometry():
    with pytest.raises(ValidationError, match="Page geometry"):
        build_surface(make_manifest(), columns=0)
    with pytest.raises(ValidationError, match="Canvas"):
        build_surface(make_manifest(), size=(0, 320))


def test_surface_validates_and_round_trips(tmp_path):
    path = write_surface(make_manifest(), tmp_path / "reverb.tosc")
    assert path.exists()
    assert not py2tosc.load(path).validate()
    assert len(find_faders(py2tosc.load(path))) == 2


def test_write_surface_xml_form(tmp_path):
    path = write_surface(make_manifest(), tmp_path / "reverb.xml")
    assert path.read_text(encoding="utf-8").startswith("<?xml")


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------


def test_emit_writes_surface_and_pd_receiver(tmp_path):
    result = emit(make_manifest(), tmp_path, "reverb", platform="pd")
    assert result.surface == tmp_path / "reverb.tosc"
    assert [p.name for p in result.receivers] == ["reverb_osc.pd"]
    assert all(p.exists() for p in result.paths)


def test_emit_writes_no_receiver_for_plugin_formats(tmp_path):
    result = emit(make_manifest(), tmp_path, "reverb", platform="clap")
    assert result.receivers == []


def test_emit_namespace_follows_the_plugin_name_not_gen_name(tmp_path):
    # A gen~ export's internal name is often an export artifact; the surface
    # should be addressed by what the user called the plugin.
    manifest = make_manifest(gen_name="gen_exported")
    emit(manifest, tmp_path, "reverb", platform="pd")
    assert "route reverb" in (tmp_path / "reverb_osc.pd").read_text()
    doc = py2tosc.load(tmp_path / "reverb.tosc")
    addresses = [
        "".join(str(p.value) for p in m.path)
        for f in find_faders(doc)
        for m in f.messages
        if isinstance(m, py2tosc.OscMessage)
    ]
    assert all(a.startswith("/reverb/") for a in addresses)


def test_emit_filename_overrides_only_the_surface(tmp_path):
    result = emit(
        make_manifest(),
        tmp_path,
        "reverb",
        platform="pd",
        filename="custom.tosc",
    )
    assert result.surface.name == "custom.tosc"
    assert result.receivers[0].name == "reverb_osc.pd"


def test_emit_receivers_can_be_suppressed(tmp_path):
    result = emit(
        make_manifest(),
        tmp_path,
        "reverb",
        platform="pd",
        options=ToscOptions(receivers=False),
    )
    assert result.receivers == []


def test_emit_without_osc_writes_no_receiver(tmp_path):
    # A receiver with nothing addressed to it would be dead code.
    result = emit(
        make_manifest(),
        tmp_path,
        "reverb",
        platform="pd",
        options=ToscOptions(osc=False),
    )
    assert result.receivers == []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_init_writes_surface_and_receiver(tmp_path, gigaverb_export):
    out = tmp_path / "proj"
    rc = main(
        [
            str(gigaverb_export),
            "-n",
            "gigaverb",
            "-p",
            "pd",
            "--tosc",
            "--no-build",
            "-o",
            str(out),
        ]
    )
    assert rc == 0
    assert (out / "gigaverb.tosc").exists()
    assert (out / "gigaverb_osc.pd").exists()


def test_cli_init_records_the_name_in_the_project_marker(tmp_path, gigaverb_export):
    out = tmp_path / "proj"
    assert (
        main(
            [
                str(gigaverb_export),
                "-n",
                "gigaverb",
                "-p",
                "pd",
                "--no-build",
                "-o",
                str(out),
            ]
        )
        == 0
    )
    marker = json.loads((out / ".gen-dsp.json").read_text())
    assert marker["name"] == "gigaverb"
    assert marker["platform"] == "pd"


def test_cli_init_rejects_a_bad_port(tmp_path, gigaverb_export, capsys):
    rc = main(
        [
            str(gigaverb_export),
            "-p",
            "pd",
            "--tosc",
            "--tosc-port",
            "0",
            "--no-build",
            "-o",
            str(tmp_path / "proj"),
        ]
    )
    assert rc == 1
    assert "--tosc-port" in capsys.readouterr().err


def test_cli_tosc_from_export(tmp_path, gigaverb_export):
    rc = main(["tosc", str(gigaverb_export), "-n", "gigaverb", "-o", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "gigaverb.tosc").exists()


def test_cli_tosc_from_manifest_json(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(make_manifest().to_json())
    rc = main(["tosc", str(manifest_path), "-o", str(tmp_path / "out")])
    assert rc == 0
    assert (tmp_path / "out" / "reverb.tosc").exists()


def test_cli_tosc_from_project_reuses_platform_and_name(tmp_path, gigaverb_export):
    project = tmp_path / "proj"
    assert (
        main(
            [
                str(gigaverb_export),
                "-n",
                "gigaverb",
                "-p",
                "pd",
                "--no-build",
                "-o",
                str(project),
            ]
        )
        == 0
    )
    assert main(["tosc", str(project)]) == 0
    assert (project / "gigaverb.tosc").exists()
    assert (project / "gigaverb_osc.pd").exists()


def test_cli_tosc_receiver_override(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(make_manifest().to_json())
    rc = main(
        [
            "tosc",
            str(manifest_path),
            "--receiver",
            "sc",
            "-o",
            str(tmp_path / "out"),
        ]
    )
    assert rc == 0
    assert (tmp_path / "out" / "reverb_osc.scd").exists()


def test_cli_tosc_explicit_output_file(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(make_manifest().to_json())
    target = tmp_path / "out" / "surface.xml"
    assert main(["tosc", str(manifest_path), "-o", str(target)]) == 0
    assert target.read_text(encoding="utf-8").startswith("<?xml")


def test_cli_tosc_size_and_geometry(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(make_manifest().to_json())
    rc = main(
        [
            "tosc",
            str(manifest_path),
            "--size",
            "1024x768",
            "--columns",
            "2",
            "--rows",
            "1",
            "-o",
            str(tmp_path / "out"),
        ]
    )
    assert rc == 0
    doc = py2tosc.load(tmp_path / "out" / "reverb.tosc")
    root = doc.root
    assert (root.frame.w, root.frame.h) == (1024, 768)


def test_cli_tosc_rejects_a_bad_size(tmp_path, capsys):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(make_manifest().to_json())
    rc = main(["tosc", str(manifest_path), "--size", "big", "-o", str(tmp_path)])
    assert rc == 1
    assert "--size" in capsys.readouterr().err


def test_cli_tosc_reports_a_missing_source(tmp_path, capsys):
    rc = main(["tosc", str(tmp_path / "nope")])
    assert rc == 1
    assert "not found" in capsys.readouterr().err


def test_cli_tosc_reports_a_manifest_with_no_parameters(tmp_path, capsys):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(make_manifest(params=[]).to_json())
    rc = main(["tosc", str(manifest_path), "-o", str(tmp_path / "out")])
    assert rc == 1
    assert "no parameters" in capsys.readouterr().err
