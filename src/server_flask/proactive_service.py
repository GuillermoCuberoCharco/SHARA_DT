"""Reserve a greeting until this connection either delivers or abandons it."""
from time import monotonic


class ProactiveService:
    COOLDOWN = 30 * 60

    def __init__(self):
        self.pending = {}
        self.delivered_until = {}

    def reserve(self, account, sid):
        now = monotonic()
        self.delivered_until = {
            name: until for name, until in self.delivered_until.items() if until > now
        }
        if account in self.pending or account in self.delivered_until:
            return False
        self.pending[account] = sid
        return True

    def release(self, account, sid, played=False):
        if self.pending.get(account) == sid:
            del self.pending[account]
            if played:
                self.delivered_until[account] = monotonic() + self.COOLDOWN
