import unittest

from oos.signals import Experiment, ResultAction, Signal, SignalType


class SignalExperimentTests(unittest.TestCase):
    def test_signal_types_are_kept_separate(self) -> None:
        experiment = Experiment(
            experiment_id="exp-1",
            purpose="Test",
            question="Which option?",
            question_version="v1",
        )
        experiment.add_signal(
            Signal(
                signal_id="s1",
                experiment_id="exp-1",
                question_version="v1",
                signal_type=SignalType.MODEL_JUDGMENT,
                source_id="model-a",
                response="A",
                timestamp="2026-09-25T00:00:00Z",
                population_or_model="model-a",
            )
        )
        experiment.add_signal(
            Signal(
                signal_id="s2",
                experiment_id="exp-1",
                question_version="v1",
                signal_type=SignalType.HUMAN_STATED_SIGNAL,
                source_id="human-sample-1",
                response="B",
                timestamp="2026-09-25T00:01:00Z",
                population_or_model="linkedin-followers",
                sampling_method="voluntary_response",
            )
        )

        vector = experiment.signal_vector()
        self.assertEqual(vector["MODEL_JUDGMENT"], 1)
        self.assertEqual(vector["HUMAN_STATED_SIGNAL"], 1)
        self.assertEqual(vector["EVIDENCE"], 0)

    def test_human_stated_signal_requires_population(self) -> None:
        experiment = Experiment(
            experiment_id="exp-1",
            purpose="Test",
            question="Question",
            question_version="v1",
        )
        with self.assertRaisesRegex(ValueError, "human_signal_population_required"):
            experiment.add_signal(
                Signal(
                    signal_id="s1",
                    experiment_id="exp-1",
                    question_version="v1",
                    signal_type=SignalType.HUMAN_STATED_SIGNAL,
                    source_id="h1",
                    response="yes",
                    timestamp="2026-09-25T00:00:00Z",
                )
            )

    def test_mixed_signals_have_no_truth_score(self) -> None:
        experiment = Experiment(
            experiment_id="exp-1",
            purpose="Test",
            question="Question",
            question_version="v1",
            resulting_action=ResultAction.FURTHER_EXPERIMENT,
        )
        with self.assertRaisesRegex(RuntimeError, "must_not_be_collapsed"):
            experiment.truth_score()


if __name__ == "__main__":
    unittest.main()
