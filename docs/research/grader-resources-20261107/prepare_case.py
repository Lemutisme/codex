"""Import the pinned image and bind the repaired grading profile; no solver."""
import json
from pathlib import Path

from grader_image import import_image

ROOT = Path(__file__).resolve().parent


def prepare_registry(task):
    case = ROOT / 'inputs/cases' / task
    case.mkdir(parents=True, exist_ok=True)
    original = Path('/data/ProContract/programbench-sol61-20261104')
    config = json.loads((original/'inputs/cases'/task/'image.json').read_text())['config_id']
    image, alias = import_image(task, config)
    path = case / 'canonical-registry.json'
    if path.exists():
        assert json.loads(path.read_text())['tasks'][task]['image'] == image
        return
    template = json.loads((ROOT/'registry-template.json').read_text())
    template.update(blob_root=str((ROOT/'inputs/evaluation-blobs').resolve()),
        blob_manifest=str(ROOT/'inputs/blob-manifest.json'), pins_file=str(case/'canonical-pins.json'),
        grader_requirements=json.loads((ROOT/'grader-requirements-by-task.json').read_text())[task],
        test_workspace=json.loads((ROOT/'plan.json').read_text())['artifacts'][task]['test_workspace'],
        tasks={task:{'image':image, 'image_tag':alias,
                     'total':json.loads((ROOT/'fixture-metadata.json').read_text())[task]['total']}})
    path.write_text(json.dumps(template, indent=2)+'\n')
