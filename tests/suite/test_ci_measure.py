"""Check opt-in profiling preserves pytest outcomes and accounts for worker costs."""

import argparse
import json
import os
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.suite import ci_measure

REPO = Path(__file__).resolve().parents[2]


def test_auto_workers_preserves_affinity_before_psutil(monkeypatch):
    monkeypatch.setattr(os, "sched_getaffinity", lambda pid: {2, 4, 6}, raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 24)
    assert ci_measure.automatic_workers() == 3


def test_auto_workers_uses_logical_count_without_affinity(monkeypatch):
    monkeypatch.delattr(os, "sched_getaffinity", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 8)
    assert ci_measure.automatic_workers() == 8


def test_samples_keep_exited_cpu_and_do_not_add_successive_rss_samples():
    class Process:
        def __init__(self, pid, rss, cpu):
            self.pid, self.rss, self.cpu = pid, rss, cpu
            self.descendants = []

        def oneshot(self):
            return nullcontext()

        def create_time(self):
            return 1

        def memory_info(self):
            return SimpleNamespace(rss=self.rss)

        def cpu_times(self):
            return SimpleNamespace(user=self.cpu, system=0)

        def children(self, recursive):
            return self.descendants

    parent = Process(1, 10, 2)
    parent.descendants = [Process(2, 20, 3)]
    samples = ci_measure.Samples(SimpleNamespace(Error=RuntimeError), parent)
    samples.take()
    parent.descendants = []
    parent.cpu = 4
    samples.take()
    assert samples.peak_rss == 30
    assert sum(samples.cpu.values()) == 7
    assert samples.peak_processes == 2


@pytest.mark.parametrize("workers", [0, 2])
def test_plugin_preserves_failures_and_complete_file_costs(tmp_path, workers):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_example.py").write_text(
        "def test_pass():\n    assert True\ndef test_fail():\n    assert False\n",
        encoding="utf-8",
    )
    output = tmp_path / "profile"
    env = os.environ.copy()
    env["WISH_CI_PROFILE_DIR"] = str(output)
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "tools.suite.ci_profile", "-n", str(workers),
         "--dist", "loadgroup", "-q", str(tmp_path)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    main = json.loads((output / "pytest-main.json").read_text())
    assert main["collected_tests"] == 2
    assert main["exit_code"] == 1
    assert len(main["selected_workers"]) == workers
    assert sum(row["reports"] for row in main["files"].values()) == 6
    profiles = [json.loads(path.read_text()) for path in output.glob("pytest-gw*.json")]
    if workers:
        assert len(profiles) == workers
        assert all(profile["collected_tests"] == 2 for profile in profiles)
        assert all(profile["collection_seconds"] > 0 for profile in profiles)
    else:
        assert main["collection_seconds"] > 0


def test_wrapper_reports_child_failure_and_keeps_explicit_worker_count(tmp_path, monkeypatch):
    class Child:
        pid = 123
        returncode = 5

        def poll(self):
            return self.returncode

    seen = {}

    def start(command, env):
        seen.update(command=command, env=env)
        return Child()

    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "7")
    monkeypatch.setattr(ci_measure.subprocess, "Popen", start)
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(
        Process=lambda pid: object(), cpu_count=lambda logical: 4,
    ))
    assert ci_measure.main(["--output", str(tmp_path), "--", "-q"]) == 5
    report = json.loads((tmp_path / "resources.json").read_text())
    assert report["exit_code"] == 5
    assert seen["env"]["PYTEST_XDIST_AUTO_NUM_WORKERS"] == "7"
    assert seen["command"][-1] == "-q"
    assert "--" not in seen["command"]


def test_stop_tree_kills_descendants_that_ignore_termination():
    events = []

    class Process:
        def __init__(self, name):
            self.name = name

        def children(self, recursive):
            return [descendant]

        def terminate(self):
            events.append((self.name, "terminate"))

        def kill(self):
            events.append((self.name, "kill"))

    parent, descendant = Process("parent"), Process("descendant")
    psutil = SimpleNamespace(
        Error=RuntimeError, wait_procs=lambda processes, timeout: ([parent], [descendant]),
    )
    ci_measure.stop_tree(psutil, parent)
    assert events == [("descendant", "terminate"), ("parent", "terminate"),
                      ("descendant", "kill")]


def test_stop_tree_still_terminates_parent_when_children_are_inaccessible():
    events = []

    class AccessDenied(RuntimeError):
        pass

    class Process:
        def children(self, recursive):
            raise AccessDenied()

        def terminate(self):
            events.append("terminate")

    parent = Process()
    psutil = SimpleNamespace(
        Error=RuntimeError, AccessDenied=AccessDenied,
        wait_procs=lambda processes, timeout: (processes, []),
    )
    ci_measure.stop_tree(psutil, parent)
    assert events == ["terminate"]


@pytest.mark.parametrize("signum", [ci_measure.signal.SIGTERM, ci_measure.signal.SIGINT])
def test_cancellation_bounds_wait_even_when_process_remains_alive(tmp_path, monkeypatch, signum):
    events = []
    handlers = {}

    class AccessDenied(RuntimeError):
        pass

    class Process:
        def children(self, recursive):
            raise AccessDenied()

        def terminate(self):
            events.append("terminate")
            raise AccessDenied()

        def kill(self):
            raise AccessDenied()

    class Child:
        pid = 123
        returncode = None

        def poll(self):
            return None

        def wait(self, timeout=None):
            assert timeout is not None, "Cancellation attempted an unbounded wait"
            events.append("wait")
            raise subprocess.TimeoutExpired("pytest", timeout)

        def kill(self):
            events.append("kill")

    def install_signal(sig, handler):
        previous = handlers.get(sig)
        handlers[sig] = handler
        return previous

    def sample(self):
        handlers[signum](signum, None)

    monkeypatch.setattr(ci_measure.signal, "signal", install_signal)
    monkeypatch.setattr(ci_measure.Samples, "take", sample)
    monkeypatch.setattr(ci_measure.subprocess, "Popen", lambda *args, **kwargs: Child())
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(
        Error=RuntimeError, AccessDenied=AccessDenied, Process=lambda pid: Process(),
        wait_procs=lambda processes, timeout: ([], processes), cpu_count=lambda logical: 4,
    ))
    assert ci_measure.main(["--output", str(tmp_path)]) == 128 + signum
    assert "terminate" in events
    assert "kill" in events
    assert events.count("wait") <= 2
    report = json.loads((tmp_path / "resources.json").read_text())
    assert report["exit_code"] == 128 + signum
    assert report["cleanup_complete"] is False


def test_wrapper_plans_shard_once_and_records_selected_weight_provenance(tmp_path, monkeypatch):
    from tools.suite import ci_shard

    files = ("tests/test_a.py", "tests/test_b.py")
    weights = {files[0]: 3, files[1]: 2}
    sha = "abcde12345" * 4
    weight_path = tmp_path / "weights.json"
    weight_path.write_text(json.dumps({
        "version": 1, "platforms": {"linux": {
            "weights": weights, "source_sha": sha, "run_id": 123,
        }},
    }))
    calls = []

    def plan(root, inventory, measured, count):
        calls.append((inventory, measured, count))
        return {"version": 1, "files": list(files), "shards": [[files[0]], [files[1]]],
                "seconds": [3, 2], "groups": {}}

    monkeypatch.setattr(ci_shard, "inventory", lambda root: (*files, "tests/generate/test_generated.py"))
    monkeypatch.setattr(ci_shard, "make_plan", plan)
    seen = {}

    def start(command, env):
        seen["command"] = command
        return SimpleNamespace(pid=123, returncode=0, poll=lambda: 0)

    monkeypatch.setattr(ci_measure.subprocess, "Popen", start)
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(
        Process=lambda pid: object(), cpu_count=lambda logical: 4,
    ))
    output = tmp_path / "output"
    assert ci_measure.main([
        "--output", str(output), "--shard-index", "1", "--weights", str(weight_path),
        "--weight-key", "linux", "--", "-n", "2",
    ]) == 0
    assert calls == [(files, weights, 2)]
    command = seen["command"]
    assert command[command.index("--ci-shard-index") + 1] == "1"
    path = Path(next(option.partition("=")[2] for option in command
                     if option.startswith("--ci-shard-plan=")))
    assert path.is_absolute()
    assert json.loads(path.read_text())["shards"] == [[files[0]], [files[1]]]
    report = json.loads((output / "resources.json").read_text())
    assert report["shard"]["source_sha"] == sha
    assert report["shard"]["run_id"] == 123
    assert report["shard"]["selected_files"] == [files[1]]
    assert report["shard"]["estimated_seconds"] == 2
    assert report["shard"]["unmeasured_files"] == []
    assert report["shard"]["excluded_files"] == ["tests/generate/test_generated.py"]
    assert "--ignore=tests/generate/test_generated.py" in command


def test_wrapper_passes_four_shard_count_and_failure_list(tmp_path, monkeypatch):
    from tools.suite import ci_shard

    files = tuple(f'tests/test_{i}.py' for i in range(4))
    weights = tmp_path / 'weights.json'
    weights.write_text(json.dumps({
        'version': 1, 'platforms': {'linux': {
            'weights': dict.fromkeys(files, 1),
            'source_sha': 'a' * 40, 'run_id': 123,
        }},
    }))
    monkeypatch.setattr(ci_shard, 'inventory', lambda root: files)
    counts = []

    def plan(root, inventory, measured, count):
        counts.append(count)
        return {'version': 1, 'files': list(files), 'shards': [[name] for name in files],
                'seconds': [1] * count, 'groups': {}}

    monkeypatch.setattr(ci_shard, 'make_plan', plan)
    commands = []

    def start(command, env):
        commands.append(command)
        return SimpleNamespace(pid=123, returncode=0, poll=lambda: 0)

    monkeypatch.setattr(ci_measure.subprocess, 'Popen', start)
    monkeypatch.setitem(sys.modules, 'psutil', SimpleNamespace(
        Process=lambda pid: object(), cpu_count=lambda logical: 4,
    ))
    failures = tmp_path / 'failures.json'
    failures.write_text('[]')
    monkeypatch.setenv('WISH_CI_PRIOR_FAILURES_JSON', '["tests/test_0.py::test_other"]')
    output = tmp_path / 'output'
    assert ci_measure.main([
        '--output', str(output), '--shard-index', '3', '--shard-count', '4',
        '--weights', str(weights), '--weight-key', 'linux',
        '--prior-failures', str(failures), '--', '-q',
    ]) == 0
    assert counts == [4]
    report = json.loads((output / 'resources.json').read_text())
    assert report['shard']['count'] == 4
    assert report['full_shard_run'] is True
    assert f'--wish-prior-failures={failures}' in commands[0]
    assert not (output / 'prior-failures.json').exists()


@pytest.mark.parametrize('use_env', [False, True])
def test_external_failure_list_preserves_pytest_testpaths(tmp_path, use_env):
    project = tmp_path / 'project'
    (project / 'tests').mkdir(parents=True)
    (project / 'livetests').mkdir()
    (project / 'pyproject.toml').write_text(
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n", encoding='utf-8')
    (project / 'conftest.py').write_text(
        'def pytest_addoption(parser):\n'
        '    parser.addoption("--wish-prior-failures")\n', encoding='utf-8')
    (project / 'tests' / 'test_selected.py').write_text(
        'def test_selected(): pass\n', encoding='utf-8')
    (project / 'livetests' / 'test_outside.py').write_text(
        'raise RuntimeError("Outside configured testpaths")\n', encoding='utf-8')
    failures = tmp_path / 'prior-failures.json'
    failures.write_text('[]', encoding='utf-8')
    output = tmp_path / 'profile'
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join(filter(None, [str(REPO), env.get('PYTHONPATH')]))
    if use_env:
        env['WISH_CI_PRIOR_FAILURES_JSON'] = '["tests/test_selected.py::test_selected"]'
    else:
        env.pop('WISH_CI_PRIOR_FAILURES_JSON', None)
    source = [] if use_env else ['--prior-failures', str(failures)]
    result = subprocess.run(
        [sys.executable, str(REPO / 'tools/suite/ci_measure.py'),
         '--output', str(output), *source, '--', '-q'],
        cwd=project, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    profile = json.loads((output / 'pytest-main.json').read_text())
    assert profile['collected_tests'] == 1
    assert set(profile['files']) == {'tests/test_selected.py'}
    resources = json.loads((output / 'resources.json').read_text())
    selected = output / 'prior-failures.json' if use_env else failures
    assert f'--wish-prior-failures={selected}' in resources['command']
    if use_env:
        assert json.loads(selected.read_text()) == ['tests/test_selected.py::test_selected']


@pytest.mark.parametrize('raw', [None, '', '[]', '{bad', '{}', '[1]', '[""]',
                                  '["tests/test_a.py::test_a\\nnext"]'])
def test_invalid_prior_failure_env_does_not_select_a_file(tmp_path, monkeypatch, raw):
    if raw is None:
        monkeypatch.delenv('WISH_CI_PRIOR_FAILURES_JSON', raising=False)
    else:
        monkeypatch.setenv('WISH_CI_PRIOR_FAILURES_JSON', raw)
    assert ci_measure.prior_failures_option(None, tmp_path) is None
    assert not (tmp_path / 'prior-failures.json').exists()


def test_external_shard_plan_keeps_pytest_testpaths(tmp_path, monkeypatch):
    from tools.suite import ci_shard

    project = tmp_path / "project"
    (project / "tests").mkdir(parents=True)
    (project / "livetests").mkdir()
    (project / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n", encoding="utf-8")
    (project / "tests" / "test_selected.py").write_text("def test_selected(): pass\n")
    (project / "tests" / "test_unselected.py").write_text("def test_unselected(): pass\n")
    (project / "livetests" / "test_emulator.py").write_text(
        "raise RuntimeError('livetests was imported')\n", encoding="utf-8")
    weights = tmp_path / "weights.json"
    weights.write_text(json.dumps({
        "version": 1,
        "platforms": {"linux": {
            "weights": {"tests/test_selected.py": 1},
            "source_sha": "a" * 40,
            "run_id": 123,
        }},
    }), encoding="utf-8")
    monkeypatch.setattr(ci_shard, "inventory", lambda root: (
        "tests/test_selected.py", "tests/test_unselected.py"))
    monkeypatch.setattr(ci_shard, "make_plan", lambda root, files, measured, count: {
        "version": 1,
        "files": ["tests/test_selected.py", "tests/test_unselected.py"],
        "shards": [["tests/test_selected.py"], ["tests/test_unselected.py"]],
        "seconds": [1, 1],
        "groups": {},
    })
    args = SimpleNamespace(shard_index=0, shard_count=2, weights=weights, weight_key="linux")
    shard_options, _ = ci_measure.shard_arguments(
        argparse.ArgumentParser(), args, tmp_path / "outside-output")
    env = os.environ.copy()
    repository = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [repository, env.get("PYTHONPATH")]))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *shard_options, "--collect-only", "-q"],
        cwd=project, env=env, capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "tests/test_selected.py" in result.stdout
    assert "livetests/test_emulator.py" not in result.stdout


@pytest.mark.parametrize("options", [
    ["--shard-index", "0"], ["--weight-key", "linux"],
    ["--weights", "missing.json"], ["--shard-index", "2"],
    ["--shard-count", "4"], ["--shard-count", "0"],
])
def test_incomplete_shard_options_stop_before_pytest(tmp_path, monkeypatch, options):
    monkeypatch.setattr(ci_measure.subprocess, "Popen", lambda *a, **kw: pytest.fail("Started pytest"))
    with pytest.raises(SystemExit) as stopped:
        ci_measure.main(["--output", str(tmp_path), *options])
    assert stopped.value.code == 2


@pytest.mark.parametrize("change", [
    {"version": 2}, {"platforms": []}, {"platforms": {}},
    {"weights": []}, {"weights": {"tests/test_a.py": -1}},
    {"weights": {"tests/test_a.py": float("nan")}},
    {"source_sha": "abc"}, {"run_id": True}, {"run_id": 0},
])
def test_invalid_weight_data_stops_before_pytest(tmp_path, monkeypatch, change):
    from tools.suite import ci_shard

    selected = {"weights": {}, "source_sha": "a" * 40, "run_id": "123"}
    data = {"version": 1, "platforms": {"linux": selected}}
    for key, value in change.items():
        (data if key in ("version", "platforms") else selected)[key] = value
    weight_path = tmp_path / "weights.json"
    weight_path.write_text(json.dumps(data))
    monkeypatch.setattr(ci_shard, "inventory", lambda root: ())
    monkeypatch.setattr(ci_measure.subprocess, "Popen", lambda *a, **kw: pytest.fail("Started pytest"))
    with pytest.raises(SystemExit) as stopped:
        ci_measure.main(["--output", str(tmp_path), "--shard-index", "0",
                         "--weights", str(weight_path), "--weight-key", "linux"])
    assert stopped.value.code == 2
