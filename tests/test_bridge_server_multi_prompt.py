import contextlib
import io
import pathlib
import sys
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import bridge_server


class _ModelWithoutPerSegmentSeeds:
    def __init__(self):
        self.kwargs = None

    def __call__(
        self,
        prompts,
        num_frames,
        *,
        constraint_lst,
        num_denoising_steps,
        num_samples,
        multi_prompt,
        num_transition_frames,
        post_processing,
        return_numpy,
    ):
        self.kwargs = {
            "constraint_lst": constraint_lst,
            "num_denoising_steps": num_denoising_steps,
            "num_samples": num_samples,
            "multi_prompt": multi_prompt,
            "num_transition_frames": num_transition_frames,
            "post_processing": post_processing,
            "return_numpy": return_numpy,
        }
        return {"prompts": prompts, "num_frames": num_frames}


class _ModelWithPerSegmentSeeds(_ModelWithoutPerSegmentSeeds):
    def __call__(
        self,
        prompts,
        num_frames,
        *,
        constraint_lst,
        num_denoising_steps,
        num_samples,
        multi_prompt,
        num_transition_frames,
        post_processing,
        return_numpy,
        seeds=None,
    ):
        result = super().__call__(
            prompts,
            num_frames,
            constraint_lst=constraint_lst,
            num_denoising_steps=num_denoising_steps,
            num_samples=num_samples,
            multi_prompt=multi_prompt,
            num_transition_frames=num_transition_frames,
            post_processing=post_processing,
            return_numpy=return_numpy,
        )
        self.kwargs["seeds"] = seeds
        return result


class MultiPromptModelCompatibilityTests(unittest.TestCase):
    def _call(self, model):
        return bridge_server._call_multi_prompt_model(
            model,
            ["hold", "turn", "walk"],
            [45, 45, 90],
            constraint_lst=[],
            diffusion_steps=100,
            num_transition_frames=8,
            seeds=[412, 413, 414],
        )

    def test_omits_seeds_for_released_model_api(self):
        model = _ModelWithoutPerSegmentSeeds()
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            result = self._call(model)

        self.assertEqual(result["num_frames"], [45, 45, 90])
        self.assertNotIn("seeds", model.kwargs)
        self.assertIn("using the first seed (412)", captured.getvalue())

    def test_passes_seeds_when_future_model_supports_them(self):
        model = _ModelWithPerSegmentSeeds()
        self._call(model)
        self.assertEqual(model.kwargs["seeds"], [412, 413, 414])


if __name__ == "__main__":
    unittest.main()
