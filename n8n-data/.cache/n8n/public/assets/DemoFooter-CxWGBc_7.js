import LogsPanel from "./LogsPanel-DSS_hDBL.js";
import { d as defineComponent, a2 as useWorkflowsStore, x as computed, e as createBlock, f as createCommentVNode, g as openBlock } from "./index-BDDH_NIA.js";
import "./AnimatedSpinner-WDiU4lXb.js";
import "./ConsumedTokensDetails.vue_vue_type_script_setup_true_lang-Bm1msTtB.js";
import "./core-BDQ6uBcD.js";
import "./canvas-tCm4ovGg.js";
const _sfc_main = /* @__PURE__ */ defineComponent({
  __name: "DemoFooter",
  setup(__props) {
    const workflowsStore = useWorkflowsStore();
    const hasExecutionData = computed(() => workflowsStore.workflowExecutionData);
    return (_ctx, _cache) => {
      return hasExecutionData.value ? (openBlock(), createBlock(LogsPanel, {
        key: 0,
        "is-read-only": true
      })) : createCommentVNode("", true);
    };
  }
});
export {
  _sfc_main as default
};
