/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable } from "mobx";
import { http, includes } from 'libs';

class Store {
  ParameterTypes = {
    'string': '文本框',
    'password': '密码框',
    'select': '下拉选择'
  }

  FileTypes = [
    {key: 'Dockerfile', value: 'dockerfile'}, 
    {key: 'YAML K8S', value: 'yaml'}
  ]

  @observable records = [];
  @observable record = {parameters: []};
  @observable isFetching = false;
  @observable formVisible = false;

  @observable f_name;
  @observable f_type;

  get dataSource() {
    let data = this.records
    if (this.f_name) data = data.filter(x => includes(x.name, this.f_name))
    if (this.f_type) data = data.filter(x => includes(x.type, this.f_type))
    return data
  }

  fetchRecords = () => {
    this.isFetching = true;
    http.get('/api/config/file/template/')
      .then((templates) => {
        this.records = templates;
      })
      .finally(() => this.isFetching = false)
  };

  showForm = (info = {parameters: []}) => {
    this.formVisible = true;
    this.record = info
  }
}

export default new Store()
