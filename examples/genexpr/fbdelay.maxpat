{
    "patcher": {
        "fileversion": 1,
        "appversion": {
            "major": 9,
            "minor": 1,
            "revision": 4,
            "architecture": "x64",
            "modernui": 1
        },
        "classnamespace": "box",
        "rect": [ 99.0, 106.0, 817.0, 688.0 ],
        "boxes": [
            {
                "box": {
                    "data": {
                        "clips": [
                            {
                                "absolutepath": "vibes-a1.aif",
                                "filename": "vibes-a1.aif",
                                "filekind": "audiofile",
                                "id": "u393007080",
                                "loop": 0,
                                "content_state": {                                }
                            }
                        ]
                    },
                    "id": "obj-21",
                    "maxclass": "playlist~",
                    "mode": "basic",
                    "numinlets": 1,
                    "numoutlets": 5,
                    "outlettype": [ "signal", "signal", "signal", "", "dictionary" ],
                    "parameter_enable": 0,
                    "patching_rect": [ 399.0, 34.0, 150.0, 30.0 ],
                    "quality": "basic",
                    "saved_attribute_attributes": {
                        "candicane2": {
                            "expression": ""
                        },
                        "candicane3": {
                            "expression": ""
                        },
                        "candicane4": {
                            "expression": ""
                        },
                        "candicane5": {
                            "expression": ""
                        },
                        "candicane6": {
                            "expression": ""
                        },
                        "candicane7": {
                            "expression": ""
                        },
                        "candicane8": {
                            "expression": ""
                        }
                    }
                }
            },
            {
                "box": {
                    "id": "obj-19",
                    "maxclass": "ezdac~",
                    "numinlets": 2,
                    "numoutlets": 0,
                    "patching_rect": [ 60.0, 624.0, 45.0, 45.0 ]
                }
            },
            {
                "box": {
                    "floatoutput": 1,
                    "id": "obj-18",
                    "maxclass": "dial",
                    "mult": 0.001,
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [ "float" ],
                    "parameter_enable": 0,
                    "patching_rect": [ 294.0, 11.0, 40.0, 40.0 ],
                    "size": 1000.0
                }
            },
            {
                "box": {
                    "id": "obj-17",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "" ],
                    "patching_rect": [ 294.0, 67.0, 51.0, 22.0 ],
                    "text": "mix_ $1"
                }
            },
            {
                "box": {
                    "floatoutput": 1,
                    "id": "obj-13",
                    "maxclass": "dial",
                    "mult": 0.001,
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [ "float" ],
                    "parameter_enable": 0,
                    "patching_rect": [ 166.0, 11.0, 40.0, 40.0 ],
                    "size": 1000.0
                }
            },
            {
                "box": {
                    "id": "obj-11",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "" ],
                    "patching_rect": [ 166.0, 67.0, 74.0, 22.0 ],
                    "text": "feedback $1"
                }
            },
            {
                "box": {
                    "id": "obj-9",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [ "" ],
                    "patching_rect": [ 60.0, 67.0, 77.0, 22.0 ],
                    "text": "delay_ms $1"
                }
            },
            {
                "box": {
                    "floatoutput": 1,
                    "id": "obj-5",
                    "maxclass": "dial",
                    "min": 1.0,
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [ "float" ],
                    "parameter_enable": 0,
                    "patching_rect": [ 60.0, 11.0, 40.0, 40.0 ],
                    "size": 999.0
                }
            },
            {
                "box": {
                    "code": "// Generated by gen-dsp (experimental .gdsp -> gen~ transpiler)\n// Graph: fbdelay\n// 1 in, 1 out, 3 param(s)\r\n\r\nParam delay_ms(250.0, min=1.0, max=1000.0);\nParam feedback(0.5, min=0.0, max=0.95);\nParam mix_(0.5, min=0.0, max=1.0);\n\nData dline(48000);\nHistory dline_wr(0.0);\n\n_sub_0 = 1.0 - mix_;\ndry = in1 * _sub_0;\nsr = samplerate;\ntap_samps = delay_ms * samplerate / 1000;\ndelayed_n = dim(dline);\ndelayed_b = dline_wr - trunc(tap_samps);\ndelayed_pos = delayed_b - delayed_n * floor(delayed_b / delayed_n);\ndelayed = peek(dline, delayed_pos);\nfb_scaled = delayed * feedback;\n_add_0 = in1 + fb_scaled;\npoke(dline, _add_0, dline_wr);\n_dw_0_wrnext = dline_wr + 1;\n_dw_0_wrnext = (_dw_0_wrnext >= dim(dline) ? _dw_0_wrnext - dim(dline) : _dw_0_wrnext);\ndline_wr = _dw_0_wrnext;\nwet = delayed * mix_;\nmix_out = dry + wet;\n\n// outputs\nout1 = mix_out;",
                    "fontface": 0,
                    "fontname": "<Monospaced>",
                    "fontsize": 12.0,
                    "id": "obj-1",
                    "maxclass": "gen.codebox~",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [ "signal" ],
                    "patching_rect": [ 60.0, 107.0, 688.0, 471.0 ]
                }
            }
        ],
        "lines": [
            {
                "patchline": {
                    "destination": [ "obj-19", 1 ],
                    "order": 0,
                    "source": [ "obj-1", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "obj-19", 0 ],
                    "order": 1,
                    "source": [ "obj-1", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "obj-1", 0 ],
                    "midpoints": [ 175.5, 98.0, 69.5, 98.0 ],
                    "source": [ "obj-11", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "obj-11", 0 ],
                    "source": [ "obj-13", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "obj-1", 0 ],
                    "midpoints": [ 303.5, 98.0, 69.5, 98.0 ],
                    "source": [ "obj-17", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "obj-17", 0 ],
                    "source": [ "obj-18", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "obj-1", 0 ],
                    "midpoints": [ 408.5, 102.98828125, 69.5, 102.98828125 ],
                    "source": [ "obj-21", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "obj-9", 0 ],
                    "source": [ "obj-5", 0 ]
                }
            },
            {
                "patchline": {
                    "destination": [ "obj-1", 0 ],
                    "midpoints": [ 69.5, 98.0, 69.5, 98.0 ],
                    "source": [ "obj-9", 0 ]
                }
            }
        ],
        "parameters": {
            "parameterbanks": {
                "0": {
                    "index": 0,
                    "name": "",
                    "parameters": [ "-", "-", "-", "-", "-", "-", "-", "-" ],
                    "buttons": [ "-", "-", "-", "-", "-", "-", "-", "-" ]
                }
            },
            "inherited_shortname": 1
        },
        "autosave": 0
    }
}