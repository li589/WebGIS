Component({
  options: {
    styleIsolation: 'apply-shared'
  },
  properties: {
    visible: {
      type: Boolean,
      value: false
    },
    group: {
      type: Object,
      value: { name: '', layers: [] }
    },
    activeLayerId: {
      type: String,
      value: ''
    },
    loading: {
      type: Boolean,
      value: false
    }
  },
  methods: {
    onSelect: function (e) {
      var id = e.currentTarget.dataset.id;
      this.triggerEvent('select', { layerId: id });
    },
    onMaskTap: function () {
      this.triggerEvent('close');
    },
    noop: function () {}
  }
});
