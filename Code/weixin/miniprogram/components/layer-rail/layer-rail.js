Component({
  options: {
    styleIsolation: 'apply-shared'
  },
  properties: {
    categories: {
      type: Array,
      value: []
    },
    activeId: {
      type: String,
      value: ''
    }
  },
  methods: {
    onTap: function (e) {
      var d = e.currentTarget.dataset || {};
      this.triggerEvent('select', { id: d.id, name: d.name });
    }
  }
});
