import unittest
from host.timing import AffineClock, AudioTimeline, AdaptiveServo


class ClockModelTests(unittest.TestCase):
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
