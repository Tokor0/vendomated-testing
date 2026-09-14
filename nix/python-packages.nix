# Robot Framework editor tooling that is not in nixpkgs yet, expressed as a
# `packageOverrides` function for a Python package set.
#
# All of these are pure-Python hatchling builds, so they need nothing beyond
# their runtime dependencies.  RobotCode ships as one distribution per
# component (they are PEP 420 namespace packages under `robotcode.`), which is
# why there are so many small derivations here.
{ lib, pkgs }:
final: prev:

let
  inherit (final) buildPythonPackage fetchPypi;

  robotcodeVersion = "2.7.0";

  # One RobotCode component. `module` is only used for the import check.
  robotcodePackage =
    {
      pname,
      hash,
      module,
      dependencies ? [ ],
      description,
    }:
    buildPythonPackage {
      inherit pname dependencies;
      version = robotcodeVersion;
      pyproject = true;

      src = fetchPypi {
        inherit pname hash;
        version = robotcodeVersion;
      };

      build-system = [ final.hatchling ];

      # The sdists ship `src/` only -- there is no test suite to run.
      doCheck = false;
      pythonImportsCheck = [ module ];

      meta = {
        inherit description;
        homepage = "https://robotcode.io";
        changelog = "https://github.com/robotcodedev/robotcode/blob/v${robotcodeVersion}/CHANGELOG.md";
        license = lib.licenses.asl20;
      };
    };
in
{
  robotcode-core = robotcodePackage {
    pname = "robotcode_core";
    hash = "sha256-OdST70w8TGch6UhxNci10iVliKPRuJR/8brK9z3AFJw=";
    module = "robotcode.core";
    description = "Shared core library for RobotCode";
    dependencies = [ final.typing-extensions ];
  };

  robotcode-plugin = robotcodePackage {
    pname = "robotcode_plugin";
    hash = "sha256-Hg9cQPCciGiudo8j9Nm7g47NHbalC/RwMErOxM8YWAA=";
    module = "robotcode.plugin";
    description = "Plugin support for the RobotCode CLI";
    dependencies = with final; [
      # Upstream forgets to declare this, but robotcode.plugin imports it.
      robotcode-core
      click
      colorama
      pluggy
      rich
      tomli-w
    ];
  };

  robotcode-robot = robotcodePackage {
    pname = "robotcode_robot";
    hash = "sha256-8pdrLvXzisJsd2m49loGOxl/dkL0zF5EnnKwOFiUN0Q=";
    module = "robotcode.robot";
    description = "Robot Framework analysis and configuration utilities for RobotCode";
    dependencies = with final; [
      platformdirs
      robotcode-core
      robotframework
    ];
  };

  robotcode-jsonrpc2 = robotcodePackage {
    pname = "robotcode_jsonrpc2";
    hash = "sha256-y0MBc5wzmJaYCZ9RvJE7Rz7x4jR8L6Xftf8+ZGLp3e4=";
    module = "robotcode.jsonrpc2";
    description = "JSON-RPC 2.0 transport used by the RobotCode language server";
    dependencies = [ final.robotcode-core ];
  };

  robotcode-modifiers = robotcodePackage {
    pname = "robotcode_modifiers";
    hash = "sha256-hkFKvSlr6VCUSSEAKLLGmKpyE/VbjO10DeCy/Lb6ThU=";
    module = "robotcode.modifiers";
    description = "Robot Framework pre-run modifiers used by RobotCode";
    dependencies = [ final.robotframework ];
  };

  robotcode = robotcodePackage {
    pname = "robotcode";
    hash = "sha256-wHAx1RA6/8DemKR0pYSyf33CWJvJCOC5CMoQlp5hdCE=";
    module = "robotcode.cli";
    description = "Command line interface for RobotCode";
    dependencies = with final; [
      robotcode-core
      robotcode-plugin
      robotcode-robot
    ];
  };

  robotcode-analyze = robotcodePackage {
    pname = "robotcode_analyze";
    hash = "sha256-Bz5HIVIyEHLkPrgMtUA1eg7fyMmvCZd9yVdbD7S9zzE=";
    module = "robotcode.analyze";
    description = "Static analysis plugin for the RobotCode CLI";
    dependencies = with final; [
      robotcode
      robotcode-plugin
      robotcode-robot
      robotframework
    ];
  };

  robotcode-runner = robotcodePackage {
    pname = "robotcode_runner";
    hash = "sha256-PCiZ+RhX62sU7lC3HZLf4IeAdRA+qZUWGI+xuI1RADU=";
    module = "robotcode.runner";
    description = "Test execution plugin for the RobotCode CLI";
    dependencies = with final; [
      robotcode
      robotcode-modifiers
      robotcode-plugin
      robotcode-robot
      robotframework
    ];
  };

  robotcode-language-server = robotcodePackage {
    pname = "robotcode_language_server";
    hash = "sha256-3lg5BV3GeXPQcGqopNd82gb6Lcbp46R4vIU1SZMANs8=";
    module = "robotcode.language_server";
    description = "Language server for Robot Framework";
    dependencies = with final; [
      robotcode
      robotcode-analyze
      robotcode-jsonrpc2
      robotcode-robot
      robotframework
    ];
  };

  robotcode-debugger = robotcodePackage {
    pname = "robotcode_debugger";
    hash = "sha256-emsxrYAcqj3pw3ymrSWnoQSsFC0GCZpY0rLCXwgbkhQ=";
    module = "robotcode.debugger";
    description = "Debug adapter for Robot Framework";
    dependencies = with final; [
      debugpy
      robotcode-jsonrpc2
      robotcode-runner
      robotframework
    ];
  };

  # Robocop 9 uses typer's vendored click (typer._click), which only exists
  # from typer 0.26 onwards; nixpkgs is still on 0.25.
  typer = prev.typer.overridePythonAttrs (old: rec {
    version = "0.27.2";
    src = pkgs.fetchFromGitHub {
      owner = "fastapi";
      repo = "typer";
      tag = version;
      hash = "sha256-vBHSJoyIQawkqqhbPJGKzPjBPm42OR/Ref/k6XFJTi8=";
    };
    # 0.27 vendors click; the old dependency list is otherwise unchanged.
    dependencies = lib.remove final.click old.dependencies;
    doCheck = false;
  });

  # Linter and formatter.  RobotCode imports this in-process for diagnostics
  # and for textDocument/formatting, so it has to live in the same interpreter.
  robotframework-robocop = buildPythonPackage rec {
    pname = "robotframework-robocop";
    version = "9.0.0";
    pyproject = true;

    src = fetchPypi {
      pname = "robotframework_robocop";
      inherit version;
      hash = "sha256-wXYzfiNaPr9WO/fAZNbC+JA2YTP4vszt9iFSwssaYAk=";
    };

    build-system = [ final.hatchling ];

    dependencies = with final; [
      jinja2
      msgpack
      pathspec
      platformdirs
      pytz
      rich
      robotframework
      tomli-w
      typer
      typing-extensions
    ];

    doCheck = false;
    pythonImportsCheck = [
      "robocop"
      "robocop.formatter.runner"
    ];

    meta = {
      description = "Static code analysis tool (linter) and code formatter for Robot Framework";
      homepage = "https://robocop.readthedocs.io";
      changelog = "https://github.com/MarketSquare/robotframework-robocop/releases/tag/v${version}";
      license = lib.licenses.asl20;
      mainProgram = "robocop";
    };
  };
}
