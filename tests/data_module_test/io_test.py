"""Test data module input-output utilities."""

from pathlib import Path
from textwrap import dedent

import pytest
import yaml
from pydantic import ValidationError

from clio_tools.data_module import ModuleInterface, modular_rulegraph_png


def load_yaml(path: Path) -> dict:
    """File with no wildcards."""
    return yaml.safe_load(path.read_text())


class TestModuleInterface:
    """Tests for INTERFACE.yaml files."""

    @pytest.fixture(
        params=["interface_simple", "interface_wildcard", "interface_no_resources"]
    )
    @staticmethod
    def interface_file_path(request) -> Path:
        """Path fixture for all testfiles."""
        return Path(__file__).parent / f"utils/{request.param}.yaml"

    @pytest.fixture
    @staticmethod
    def interface_dict(interface_file_path: Path) -> dict:
        """Loaded testfile."""
        return load_yaml(interface_file_path)

    def test_from_dict(self, interface_dict: dict):
        """Dictionary loading should work."""
        assert ModuleInterface(**interface_dict)

    def test_from_path(self, interface_file_path: Path, interface_dict: dict):
        """Loading data from YAML files should result in no alterations."""
        assert ModuleInterface.from_yaml(interface_file_path) == ModuleInterface(
            **interface_dict
        )

    def test_to_mermaid_flowchart(self, interface_dict: dict):
        """Mermaid graph generation should include all file I/O elements."""
        interface = ModuleInterface(**interface_dict)
        mermaid_txt = interface.to_mermaid_flowchart("test")
        assert all([i in mermaid_txt for i in interface.pathvars.user_resources])
        assert all([i in mermaid_txt for i in interface.pathvars.results])

    @pytest.mark.parametrize(
        "semver", ["0.1.0", "2.0.0", "3.0.0-alpha", "1.0.0-alpha.beta"]
    )
    def test_modelblocks_convention_semver(self, semver: str, interface_dict: dict):
        """Modelblocks convention should accept semver, with or without 'v'."""
        interface_dict["convention_version"] = semver
        assert ModuleInterface(**interface_dict)
        interface_dict["convention_version"] = f"v{semver}"
        assert ModuleInterface(**interface_dict)

    @pytest.fixture
    @staticmethod
    def interface_w_wilcards():
        """File with wildcards configured."""
        return load_yaml(Path(__file__).parent / "utils/interface_wildcard.yaml")

    def test_wildcard_section_missing(self, interface_w_wilcards):
        """If filenames specify wildcards, they should appear in the wildcards section."""
        del interface_w_wilcards["wildcards"]
        with pytest.raises(
            ValidationError,
            match="Wildcards not specified in 'user_resources' or 'results' pathvars:",
        ):
            ModuleInterface(**interface_w_wilcards)

    def test_wildcard_not_in_filename(self, interface_w_wilcards):
        """All values in the wildcards section should appear in filenames at least once."""
        interface_w_wilcards["pathvars"]["user_resources"]["text"]["default"] = (
            "<resources>/user/no_wildcard.txt"
        )
        with pytest.raises(ValidationError, match="Unused wildcards found"):
            ModuleInterface(**interface_w_wilcards)

    def test_mermaid_flow_diagram_text(self, interface_w_wilcards):
        """The generated diagram should be correct and use 4 space indentation."""
        expected = dedent("""\
            ---
            title: biomass
            ---
            flowchart LR
            M((biomass))
            C1[/"`**user**
                table
                text
                `"/] --> M
            M --> O1("`**results**
                stuff
                more_stuff
                `")""")
        interface = ModuleInterface(**interface_w_wilcards)
        generated = interface.to_mermaid_flowchart("biomass")
        assert expected == generated


class TestModularRulegraphPNG:
    """Test the generator of 'friendly' modular graphs."""

    @pytest.fixture(scope="class")
    def rulegraph_path(self):
        """Pre made test file."""
        return "tests/data_module_test/utils/rulegraph.dot"

    @pytest.fixture
    def modular_graph_path(self, tmp_path):
        """Temporary location for generated test files."""
        return tmp_path / "modulegraph.png"

    @pytest.mark.parametrize(
        "prefixes", [("module_biofuels"), ("module_hydropower", "module_wind_pv")]
    )
    def test_modulegraph_success(self, rulegraph_path, modular_graph_path, prefixes):
        """Correct configurations should run without issues."""
        modular_rulegraph_png(rulegraph_path, modular_graph_path, prefixes)
        assert modular_graph_path.exists()

    @pytest.mark.parametrize("prefix", [("module_fail"), ("module _ hydropower")])
    def test_modulegraph_incorrect_prefix(
        self, rulegraph_path, modular_graph_path, prefix
    ):
        """Users should be warned when requesting incorrect module names."""
        with pytest.raises(ValueError, match=f"Prefix not found: {prefix}."):
            modular_rulegraph_png(rulegraph_path, modular_graph_path, prefix)

    def test_modulegraph_incorrect_file_input(self, modular_graph_path):
        """Users should be warned if passing an incorrect file."""
        with pytest.raises(ValueError, match="Only .dot files can be processed."):
            modular_rulegraph_png(
                "some_file.txt", modular_graph_path, "module_biofuels"
            )
