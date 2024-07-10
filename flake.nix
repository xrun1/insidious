{
    inputs = {
        nixpkgs.url = "github:redyf/nixpkgs/update-yt-dlp";
        flake-utils.url = "github:numtide/flake-utils";
        construct.url = "github:construct/construct/a6603d7821480fb5a4e6665c6fd8028ce574c4bd";
        construct.flake = false;
        pymp4.url = "github:devine-dl/pymp4/construct-2.10-patch";
        pymp4.flake = false;
    };

    outputs = inputs @ { self, nixpkgs, flake-utils, ...}: {
        nixosModules.default = import ./os.nix self;

    } // (flake-utils.lib.eachDefaultSystem (sys: let
        pkgs = nixpkgs.legacyPackages.${sys};
        pypkgs = pkgs.python311Packages;
        construct21068 = pypkgs.construct.overrideAttrs {
            version = "2.10.68";
            src = inputs.construct;
        };
        pymp4 = pypkgs.buildPythonPackage {
            name = "pymp4";
            src = inputs.pymp4;
            pyproject = true;
            nativeBuildInputs = with pypkgs; [poetry-core];
            propagatedBuildInputs = [construct21068];
        };
    in {
        packages.default = pypkgs.buildPythonPackage rec {
            pname = "insidious";
            version = "0.1.2";
            meta.mainProgram = pname;
            src = ./.;
            pyproject = true;
            enableParallelBuild = true;
            nativeBuildInputs = [pypkgs.poetry-core];
            propagatedBuildInputs = with pypkgs; [
                typing-extensions
                fastapi
                jinja2
                pydantic
                uvicorn
                watchfiles
                yt-dlp
                docopt
                httpx
                backoff
                appdirs
                websockets
                lz4
                pure-protobuf
                pymp4 construct21068
            ];
        };
        devShells.default = pkgs.mkShell {
            inputsFrom = [self.packages.${sys}.default];
            packages = with pkgs; [
                ruff pyright  # linting
                pypkgs.ipdb pypkgs.rich pypkgs.pyperclip  # debugging
                wget  # ./update-static.sh
            ];
            shellHook = ''export PYTHONBREAKPOINT=ipdb.set_trace'';
        };
    }));
}
