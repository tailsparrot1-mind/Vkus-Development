from dataclasses import dataclass
from datetime import datetime
import traceback

@dataclass
class CheckResult:
    key: str
    title: str
    ok: bool
    detail: str
    url: str = ''
    duration: float = 0.0


class CheckRunner:
    def __init__(self, checks, on_start=None, on_result=None, on_log=None):
        self.checks = checks
        self.on_start = on_start
        self.on_result = on_result
        self.on_log = on_log
        self.results = {}

    def run_one(self, check):
        started = datetime.now()
        if self.on_start:
            self.on_start(check.key)
        try:
            result = check.run()
            result.duration = (datetime.now() - started).total_seconds()
        except Exception as exc:
            result = CheckResult(check.key, check.title, False, f'{type(exc).__name__}: {exc}')
            result.duration = (datetime.now() - started).total_seconds()
            if self.on_log:
                self.on_log(traceback.format_exc())
        self.results[check.key] = result
        if self.on_result:
            self.on_result(result)
        return result

    def run_all(self, stop_after_auth=True):
        results = []
        for check in self.checks:
            result = self.run_one(check)
            results.append(result)
            # Never start profile/search/etc. against an unauthenticated browser.
            # The user must finish manual VK login first.
            if stop_after_auth and check.key == 'auth' and not result.ok:
                if self.on_log:
                    self.on_log('Full check stopped: VK authentication was not confirmed.')
                break
        return results
