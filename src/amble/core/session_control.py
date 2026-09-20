"""Monotonic protocol clock: paused time never advances the stimulus."""
import time

class ProtocolClock:
    def __init__(self, phases, duration, clock=time.perf_counter, countdown=0, transition_delay=0):
        self.clock=clock; self.phases=list(phases); self.duration=duration; self.index=0
        self.started=clock();self.phase_started=self.started+countdown; self.paused_at=None; self.attempt=1; self.paused_total=0.0
        self.transition_delay=transition_delay
    @property
    def phase(self): return self.phases[min(self.index,len(self.phases)-1)]
    @property
    def paused(self): return self.paused_at is not None
    def remaining_delay(self): return max(0,self.phase_started-(self.paused_at if self.paused else self.clock()))
    def elapsed(self): return max(0,(self.paused_at if self.paused else self.clock())-self.phase_started)
    def pause(self):
        if not self.paused:self.paused_at=self.clock()
    def resume(self):
        if self.paused:
            gap=self.clock()-self.paused_at;self.phase_started+=gap;self.paused_total+=gap;self.paused_at=None
    def restart(self):
        self.attempt+=1;self.phase_started=self.clock()
        if self.paused:self.paused_at=self.phase_started
    def advance(self):
        self.index+=1;self.attempt=1;self.phase_started=self.clock()+self.transition_delay
        return self.index < len(self.phases)
