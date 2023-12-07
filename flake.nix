{
    inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    outputs = { self, nixpkgs, ...}: let
        sys = "x86_64-linux";
        pkgs = nixpkgs.legacyPackages.x86_64-linux;
        pyPkgs = pkgs.python311Packages;
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
                fastapi
                jinja2
                pydantic
                uvicorn
                watchfiles  # for watching non-.py files with uvicorn
                libsass
                yt-dlp
                docopt
            ];
        };
        devShells.${sys}.default = pkgs.mkShell {
            inputsFrom = [packages.${sys}.default];
            packages = with pyPkgs; [
                ipdb rich  # debugging
                wget  # ./update-static.sh
            ];
            shellHook = ''export PYTHONBREAKPOINT=ipdb.set_trace'';
        };
    };
}
