{
    inputs = {
        nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
        construct.url = "github:construct/construct/a6603d7821480fb5a4e6665c6fd8028ce574c4bd";
        construct.flake = false;
        pymp4.url = "github:devine-dl/pymp4/construct-2.10-patch";
        pymp4.flake = false;
    };
    outputs = inputs @ { self, nixpkgs, ...}: let
        sys = "x86_64-linux";
        pkgs = nixpkgs.legacyPackages.x86_64-linux;
        pyPkgs = pkgs.python311Packages;
        construct21068 = pyPkgs.construct.overrideAttrs {
            verson = "2.10.68";
            src = inputs.construct;
        };
        pymp4 = pyPkgs.buildPythonPackage {
            name = "pymp4";
            src = inputs.pymp4;
            pyproject = true;
            nativeBuildInputs = with pyPkgs; [poetry-core];
            propagatedBuildInputs = [construct21068];
        };
    in rec {
        packages.${sys}.default = pyPkgs.buildPythonPackage rec {
            pname = "xrtube";
            version = "0.1.0";
            meta.mainProgram = pname;
            src = ./.;
            pyproject = true;
            enableParallelBuild = true;
            nativeBuildInputs = [pyPkgs.poetry-core];
            propagatedBuildInputs = with pyPkgs; [
                typing-extensions
                fastapi
                jinja2
                pydantic
                uvicorn
                watchfiles
                libsass
                yt-dlp
                docopt
                httpx
                backoff
                appdirs
                websockets
                pillow
                pymp4 construct21068
            ];
        };
        devShells.${sys}.default = pkgs.mkShell {
            inputsFrom = [packages.${sys}.default];
            packages = with pkgs; [
                ruff nodePackages.pyright  # linting
                pyPkgs.ipdb pyPkgs.rich  # debugging
                wget  # ./update-static.sh
            ];
            shellHook = ''export PYTHONBREAKPOINT=ipdb.set_trace'';
        };
    };
}
