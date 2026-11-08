"""Static guardrails for the scoped browser renderer; runtime DOM checked separately."""
import unittest
from pathlib import Path
HTML=(Path(__file__).resolve().parents[1]/"web/index.html").read_text()
class PipelineUITests(unittest.TestCase):
 def test_pipeline_schema_additive_required_types_and_closed_children(self):
  import json
  spec=json.loads((Path(__file__).resolve().parents[1]/"docs/task-pipeline-openapi-v1.0.2.yaml").read_text());schemas=spec["components"]["schemas"]
  expected={"Pipeline":{"task_id":"string","title":"string","lead":["string","null"],"status":"string","status_label":"string","priority":"integer","created_at":{"$ref":"#/components/schemas/Epoch"},"completed_at":{"$ref":"#/components/schemas/Epoch"},"rollup":{"$ref":"#/components/schemas/Rollup"},"milestones":"array"},"Rollup":{"total":"integer","done":"integer","running":"integer","blocked":"integer","deferred":"integer","pct":"integer","planned":"integer","emergent":"integer"},"Milestone":{"id":"string","title":"string","assignee":["string","null"],"status":"string","status_label":"string","started_at":{"$ref":"#/components/schemas/Epoch"},"completed_at":{"$ref":"#/components/schemas/Epoch"},"blocked_kind":["string","null"],"emergent":"boolean","origin_label":"enum","also_under":"integer","also_under_note":["string","null"]}}
  for name,props in expected.items():
   schema=schemas[name];self.assertFalse(schema["additionalProperties"]);self.assertTrue(set(props).issubset(schema["properties"]));self.assertTrue(set(props).issubset(set(schema["required"])))
   for prop,typ in props.items():
    actual=schema["properties"][prop]
    if isinstance(typ,dict):self.assertEqual(actual.get("$ref"),typ["$ref"])
    elif typ=="enum":self.assertEqual(actual["enum"],[None,"added mid-flight"])
    else:self.assertEqual(actual["type"],typ)
  state=schemas["PipelineStateExtension"];self.assertTrue(set(["pipeline","pipeline_available","pipeline_error","pipelines_omitted"]).issubset(state["required"]));self.assertEqual(state["properties"]["pipelines_omitted"],{"type":"integer","minimum":0,"description":state["properties"]["pipelines_omitted"]["description"]});self.assertNotIn("available",state["properties"])
 def test_panel_is_after_org_before_logs_without_renaming_queue(self):
  panel=HTML.index('<section class="card n12" id="taskPipelinePanel">');org=HTML.rfind('<section class="card org">',0,panel);logs=HTML.index('<section class="card logs" id="logsCard">',panel)
  self.assertLess(org,panel);self.assertLess(panel,logs);self.assertIn('<div id="taskPipelineBody"></div>',HTML[panel:logs]);self.assertIn('<h2>Task pipeline <small id="qsum">',HTML)
 def test_renderer_is_called_from_refresh_and_mapstate_and_scoped(self):
  self.assertIn('lastEventAt=Date.now();renderPipeline(state);if(!hasData(state))',HTML);self.assertIn('function mapState(state){\n  renderPipeline(state);',HTML);self.assertIn('function refreshState()',HTML)
  self.assertIn('function pipelineEscape',HTML);self.assertIn('sessionStorage.getItem("mc.pipeline.expanded."+id)',HTML);self.assertNotIn('localStorage.setItem("mc.pipeline.expanded.',HTML)
 def test_wib_empty_unavailable_and_blocked_styling(self):
  for value in ['Asia/Jakarta','WIB','Started ','Started unavailable','No decomposed tasks in flight.','board unavailable','has-blocked','var(--rd)','pipeline-dot.queued{color:var(--am)}','pipeline-dot.review{color:var(--vi)}']:
   self.assertIn(value,HTML)
if __name__=="__main__":unittest.main()
