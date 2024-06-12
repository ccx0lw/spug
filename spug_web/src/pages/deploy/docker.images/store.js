/**
 * Copyright: (c) ccx0lw. https://github.com/ccx0lw/spug
 * Copyright: (c) <fcjava@163.com>
 * Released under the AGPL-3.0 License.
 */
import { observable, computed } from "mobx";
import http from 'libs/http';

class Store {
  @observable records = [];
  @observable record = {};
  @observable deploy = {};
  @observable isFetching = false;
  @observable formVisible = false;
  @observable addVisible = false;
  @observable logVisible = false;
  @observable detailVisible = false;

  @observable f_tag;
  @observable f_app_id;
  @observable f_env_id;

  @computed get dataSource() {
    let records = this.records;
    if (this.f_tag)    records = records.filter(x => x.app_rel_tags.includes(this.f_tag));
    if (this.f_app_id) records = records.filter(x => x.app_id === this.f_app_id);
    if (this.f_env_id) records = records.filter(x => x.env_id === this.f_env_id);
    return records
  }

  fetchRecords = () => {
    this.isFetching = true;
    return http.get('/api/docker_images/')
      .then(res => this.records = res)
      .finally(() => this.isFetching = false)
  };

  showForm = () => {
    this.record = {};
    this.addVisible = true
  };

  confirmAdd = (deploy) => {
    this.deploy = deploy;
    this.formVisible = true;
    this.addVisible = false;
  };

  showConsole = (info) => {
    this.record = info;
    this.logVisible = true
  };

  showDetail = (info) => {
    this.record = info;
    this.detailVisible = true
  }
}

export default new Store()
