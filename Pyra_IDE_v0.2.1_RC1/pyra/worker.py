"""One persistent, isolated Jedi process: never share its parser across threads."""

import ast
import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path


def outline(code):
    tree = ast.parse(code)
    result = []

    def visit(nodes, depth=0):
        for node in nodes:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "class" if isinstance(node, ast.ClassDef) else "def"
                result.append(
                    {"name": node.name, "line": node.lineno, "kind": kind, "depth": depth}
                )
                visit(node.body, depth + 1)

    visit(tree.body)
    return result


class Engine:
    def __init__(self):
        self.environments = {}

    def handle(self, request):
        operation = request["operation"]
        code = request["code"]
        if operation == "outline":
            target = tuple(request.get("python_version") or sys.version_info[:3])
            if target[:2] > sys.version_info[:2]:
                # Parse newer syntax with the project's interpreter. Source is never executed.
                completed = subprocess.run(
                    [request["interpreter"], "-I", str(Path(__file__).resolve())],
                    input=json.dumps({"id": 0, "operation": "outline", "code": code}) + "\n",
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=5,
                    check=True,
                    creationflags=0x08000000 if sys.platform == "win32" else 0,
                )
                response = json.loads(completed.stdout)
                if "error" in response:
                    raise ValueError(response["error"])
                return response["result"]
            try:
                return outline(code)
            except SyntaxError:
                return []
        # The initial outline needs only the stdlib, not the completion engine.
        import jedi

        root = request.get("root") or str(Path.cwd())
        interpreter = request.get("interpreter", sys.executable)
        if interpreter not in self.environments:
            self.environments.clear()
            self.environments[interpreter] = jedi.create_environment(interpreter, safe=False)
        project = jedi.Project(
            root, environment_path=interpreter, added_sys_path=[root], smart_sys_path=True
        )
        script = jedi.Script(
            code=code,
            path=request.get("path") or None,
            project=project,
            environment=self.environments[interpreter],
        )
        position = {"line": request["line"], "column": request["column"]}
        if operation == "complete":
            return [c.name for c in script.complete(**position)[:150]]
        if operation == "signature":
            return [s.to_string() for s in script.get_signatures(**position)[:3]]
        if operation in {"goto", "references", "help"}:
            if operation == "goto":
                names = script.goto(**position, follow_imports=True)
            elif operation == "references":
                names = script.get_references(**position, include_builtins=False)
            else:
                names = script.infer(**position)
            return [
                {
                    "name": n.full_name or n.name,
                    "path": str(n.module_path or ""),
                    "line": n.line or 1,
                    "column": n.column or 0,
                    "doc": n.docstring()[:10000] if operation == "help" else "",
                }
                for n in names[:300]
            ]
        if operation == "rename":
            changes = script.rename(**position, new_name=request["new_name"]).get_changed_files()
            result = []
            from .storage import read_source

            for path, changed in changes.items():
                if not Path(path).resolve().is_relative_to(Path(root).resolve()):
                    raise ValueError("Переименование за пределами проекта запрещено")
                result.append(
                    {
                        "path": str(path),
                        "before": read_source(Path(path)).text,
                        "after": changed.get_new_code(),
                        "diff": changed.get_diff(),
                    }
                )
            return result
        raise ValueError(f"Unknown operation: {operation}")


def main():
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.kernel32.SetPriorityClass(
                ctypes.windll.kernel32.GetCurrentProcess(), 0x4000
            )
        else:
            os.nice(5)
    except (OSError, AttributeError):
        pass
    engine = Engine()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                result = engine.handle(request)
            response = {"id": request["id"], "result": result}
        except Exception as error:
            response = {"id": locals().get("request", {}).get("id"), "error": str(error)}
        print(json.dumps(response, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
