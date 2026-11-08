"""Static guardrails for the scoped browser renderer; runtime DOM checked separately."""
import unittest
from pathlib import Path
HTML=(Path(__file__).resolve().parents[1]/"web/index.html").read_text()
class PipelineUITests(unittest.TestCase):
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
