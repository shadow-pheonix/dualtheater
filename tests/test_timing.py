import unittest
from host.timing import AffineClock, AudioTimeline, AdaptiveServo


class ClockModelTests(unittest.TestCase):
    def test_sparse_delayed_reply_uses_the_center_of_its_supported_interval(self):
        base, offset = 20_000_000_000, 100_000_000
        clock = AffineClock()
        # An acquired asymmetric path puts the prior phase near one edge of
        # a later wider, but compatible interval. Retaining that edge doubles
        # worst-case error; the interval itself still supports <12 ms error.
        for i in range(3):
            t = base + i * 200_000_000
            clock.add(t, t + offset - 5_000_000 + 6_000_000,
                t + offset - 5_000_000 + 6_000_000, t + 12_000_000)
        self.assertIsNotNone(clock.best(base + 600_000_000))
        t = base + 4_000_000_000
        clock.add(t, t + offset + 10_000_000, t + offset + 10_000_000, t + 20_000_000)
        now = t + 1_100_000_000
        model = clock.best(now)
        self.assertIsNotNone(model)
        self.assertLess(model.uncertainty_ns, 12_000_000)
        self.assertLessEqual(abs(model.remote(now) - (now + offset)), model.uncertainty_ns)

    def test_sparse_replies_track_an_acquired_clock_but_do_not_create_or_renew_readiness(self):
        base = 20_000_000_000; offset = 100_000_000
        def add(clock, t, delay):
            self.assertTrue(clock.add(t, t + offset + delay, t + offset + delay, t + 2 * delay))
        fresh = AffineClock()
        for i in range(2): add(fresh, base + i * 200_000_000, 1_000_000)
        self.assertIsNone(fresh.best(base + 600_000_000))
        clock = AffineClock()
        for i in range(3): add(clock, base + i * 200_000_000, 1_000_000)
        first = clock.best(base + 600_000_000)
        add(clock, base + 2_000_000_000, 4_000_000)
        add(clock, base + 2_200_000_000, 6_000_000)
        # The three acquisition exchanges aged out. Two genuine current replies
        # still support the established rate and a bounded phase interval.
        tracked = clock.best(base + 3_600_000_000)
        self.assertIsNotNone(tracked)
        self.assertEqual(tracked.rate, first.rate)
        self.assertLess(tracked.uncertainty_ns, 12_000_000)
        self.assertLessEqual(abs(tracked.offset_ns - offset), tracked.uncertainty_ns)
        retained = clock.last_fit
        self.assertIsNotNone(clock.best(base + 3_800_000_000))
        self.assertEqual(clock.last_fit, retained)
        self.assertIsNone(clock.best(base + 6_000_000_000))

    def test_compatible_path_jitter_does_not_double_count_confidence(self):
        clock = AffineClock(); base = 20_000_000_000; offset = 100_000_000
        # Synthetic compatible paths, not a device/network trace.
        rows = [(0, 20), (-2, 16), (-1, 18), (5, 18), (6, 20), (3, 20), (-3, 22),
                (-2, 18), (-1, 18), (-3, 12), (4, 18), (-1, 18), (-1, 20), (0, 24)]
        for i, (midpoint_ms, rtt_ms) in enumerate(rows):
            t0 = base + i * 200_000_000; rtt = round(rtt_ms * 1e6)
            remote = t0 + offset + round(midpoint_ms * 1e6) + rtt // 2
            self.assertTrue(clock.add(t0, remote, remote, t0 + rtt))
        estimate = clock.best(base + 2_800_000_000)
        self.assertIsNotNone(estimate)
        self.assertLess(estimate.uncertainty_ns, 8_000_000)
        self.assertLessEqual(abs(estimate.offset_ns - offset), estimate.uncertainty_ns)

    def test_asymmetric_live_replies_do_not_manufacture_clock_expiry(self):
        clock = AffineClock(); base = 20_000_000_000; offset = 100_000_000
        # These three midpoint estimates differ by >2 ms, but their measured
        # delay intervals all contain the same true offset. No old fit exists.
        for i, (midpoint_ms, rtt_ms) in enumerate(((6, 14), (1, 12), (0, 6))):
            t0 = base + i * 200_000_000
            rtt = round(rtt_ms * 1e6)
            remote = t0 + offset + round(midpoint_ms * 1e6) + rtt // 2
            self.assertTrue(clock.add(t0, remote, remote, t0 + rtt))
        estimate = clock.best(base + 600_000_000)
        self.assertIsNotNone(estimate)
        self.assertLess(estimate.uncertainty_ns, 12_000_000)
        self.assertLessEqual(abs(estimate.offset_ns - offset), estimate.uncertainty_ns)

    def test_unusable_new_fit_bridges_briefly_without_renewing_holdover(self):
        clock = AffineClock(); base = 20_000_000_000; offset = 100_000_000
        for i in range(3):
            t0 = base + i * 100_000_000
            clock.add(t0, t0 + offset + 4_000_000, t0 + offset + 4_000_000, t0 + 8_000_000)
        previous = clock.best(base + 300_000_000)
        self.assertIsNotNone(previous)
        # Three inconsistent low-RTT observations cannot establish a new fit.
        # Retain only the last bounded estimate, rather than aborting on one
        # polling iteration or treating these observations as fresh confidence.
        for i, jitter in enumerate((-3_000_000, 0, 3_000_000)):
            t0 = base + 400_000_000 + i * 20_000_000
            clock.add(t0, t0 + offset + jitter + 1_000_000,
                      t0 + offset + jitter + 1_000_000, t0 + 2_000_000)
        bridged = clock.best(base + 500_000_000)
        self.assertIsNotNone(bridged)
        self.assertGreater(bridged.uncertainty_ns, previous.uncertainty_ns)
        self.assertEqual(clock.last_fit, previous)
        self.assertIsNone(clock.best(base + 1_100_000_000))

    def test_retired_rtt_minimum_does_not_expire_healthy_clock(self):
        clock = AffineClock(); base = 20_000_000_000; offset = 100_000_000
        for i in range(70):
            t0 = base + i * 200_000_000
            delay = 1_000_000 if i < 10 else 6_000_000
            clock.add(t0, t0 + offset + delay, t0 + offset + delay,
                      t0 + 2 * delay)
        now = base + 14_000_000_000
        estimate = clock.best(now)
        self.assertIsNotNone(estimate)
        self.assertLess(estimate.uncertainty_ns, 8_000_000)
        self.assertLessEqual(abs(estimate.offset_ns - offset), estimate.uncertainty_ns)

    def test_drift_large_clock_origins_and_uncertainty_cover_asymmetry(self):
        for asymmetry in (0, 500_000, -500_000):
            clock = AffineClock()
            base, offset, skew = 8_000_000_000_000_000, -7_000_000_000_000_000, .00018
            for i in range(40):
                t0 = base + i * 200_000_000
                remote = lambda t: t + offset + round((t - base) * skew)
                t1 = remote(t0 + 1_000_000 + asymmetry)
                t2 = remote(t0 + 1_100_000 + asymmetry)
                self.assertTrue(clock.add(t0, t1, t2, t0 + 2_100_000))
            now = base + 8_000_000_000
            model = clock.best(now)
            self.assertIsNotNone(model)
            self.assertAlmostEqual(model.rate, 1 + skew, places=6)
            self.assertLessEqual(abs(model.remote(now) - remote(now)), model.uncertainty_ns)
            self.assertLess(abs(model.host(remote(now)) - now), 600_000)
            self.assertIsNone(clock.best(now + 20_000_000_000))

    def test_replay_outliers_and_bad_exchanges(self):
        clock = AffineClock()
        for i in range(10):
            t = 10_000_000_000 + i * 500_000_000
            self.assertTrue(clock.add(t, t + 101_000_000, t + 101_100_000, t + 2_100_000))
        self.assertFalse(clock.add(t, t + 100, t + 200, t + 300))
        self.assertFalse(clock.add(20, 21, 19, 24))
        self.assertFalse(clock.add(1, float('nan'), 3, 4))
        self.assertTrue(clock.add(t + 1_000_000_000, t + 1_130_000_000,
                                  t + 1_130_100_000, t + 1_060_100_000))
        model = clock.best(t + 1_100_000_000)
        self.assertAlmostEqual(model.offset_ns, 100_000_000, delta=100_000)

    def test_holdover_uncertainty_grows_and_duplicate_cannot_acquire(self):
        clock = AffineClock()
        self.assertTrue(clock.add(1000, 2000, 2100, 1200))
        for _ in range(20):
            self.assertFalse(clock.add(1000, 2000, 2100, 1200))
        self.assertIsNone(clock.best(5000))
        for t in (2000, 3000): clock.add(t, t + 1000, t + 1100, t + 200)
        first = clock.best(4000)
        self.assertGreater(clock.best(2_000_004_000).uncertainty_ns, first.uncertainty_ns)


class AudioAndServoTests(unittest.TestCase):
    def test_smooth_source_settling_does_not_starve_current_anchor(self):
        timeline = AudioTimeline()
        for i in range(140):
            elapsed = i * 50
            phase = (0 if elapsed < 500 else (elapsed - 500) * .008 if elapsed < 3000
                     else 20 if elapsed < 3500 else 20 - (elapsed - 3500) * .008 if elapsed < 6000 else 0)
            anchor = timeline.add({'host_ns': 20_000_000_000 + elapsed * 1_000_000,
                'position_ms': 10000 + elapsed * 1.0003 + phase, 'uncertainty_ms': 2})
            self.assertIsNotNone(anchor)
            self.assertLess(anchor['uncertainty_ms'], 10)
            self.assertTrue(.999 <= anchor['rate'] <= 1.001)

    def test_audio_rate_and_source_offsets_are_preserved(self):
        model = AudioTimeline()
        for i in range(50):
            anchor = model.add({'host_ns': 20_000_000_000 + i * 50_000_000,
                                'position_ms': 12345 + i * 50 * 1.00015,
                                'uncertainty_ms': .2})
        self.assertAlmostEqual(anchor['rate'], 1.00015, places=6)
        self.assertAlmostEqual(anchor['position_ms'], 12345 + 49 * 50 * 1.00015, places=5)
        self.assertIsNone(model.add({'host_ns': anchor['host_ns'], 'position_ms': 0, 'uncertainty_ms': 0}))
        with self.assertRaisesRegex(ValueError, 'discontinuity'):
            model.add({'host_ns': anchor['host_ns'] + 50_000_000, 'position_ms': 0, 'uncertainty_ms': 0})

    def test_servo_persistence_uses_elapsed_time_and_rejects_repeats(self):
        servo = AdaptiveServo()
        for i in range(20):
            speed, hard = servo.update(250, i * 10_000_000, 2)
            self.assertFalse(hard)
        self.assertLess(speed, 1)
        self.assertEqual(servo.update(250, 190_000_000, 2), (None, False))
        _, hard = servo.update(250, 2_000_000_000, 2)
        self.assertTrue(hard)

    def test_servo_converges_with_drift_and_respects_uncertainty(self):
        servo = AdaptiveServo()
        error, speed = 75, 1
        for i in range(6000):
            error += (speed - 1 + .0002) * 100
            speed, hard = servo.update(error, i * 100_000_000, 2)
            self.assertFalse(hard)
            self.assertTrue(.995 <= speed <= 1.005)
        self.assertLess(abs(error), 12)
        servo.reset()
        for i in range(10): speed, _ = servo.update(12, i * 100_000_000, 20)
        self.assertEqual(speed, 1)
