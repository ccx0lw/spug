/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable, computed } from "mobx";
import http from 'libs/http';
import moment from 'moment';
import lds, { isEmpty } from 'lodash';

class Store {
  @observable records = [];
  @observable record = {};
  @observable isFetching = false;
  @observable formVisible = false;
  @observable detailVisible = false;
  @observable publishVisible = false;
  @observable publishStatus = [];  // 按环境分组的发布状态
  @observable isPublishing = false;

  @observable f_name;
  @observable f_env_id;
  @observable f_status;
  @observable f_s_date;
  @observable f_e_date;

  @computed get dataSource() {
    let data = this.records;
    if (this.f_name) data = data.filter(x => x.name.includes(this.f_name))
    // 迭代可能包含多个环境，检查 env_ids 数组
    if (this.f_env_id) {
      const filterEnvId = Number(this.f_env_id);
      data = data.filter(x => {
        if (Array.isArray(x.env_ids) && x.env_ids.length > 0) {
          return x.env_ids.some(id => Number(id) === filterEnvId)
        }
        return Number(x.env_id) === filterEnvId
      })
    }
    if (this.f_status) data = data.filter(x => x.status === this.f_status)
    return data
  }

  fetchRecords = () => {
    this.isFetching = true;
    if (isEmpty(this.f_s_date) || isEmpty(this.f_e_date)) {
      let currentDate = new Date();
      let thirtyDaysAgo = new Date();
      thirtyDaysAgo.setDate(currentDate.getDate() - 30);

      this.f_s_date = thirtyDaysAgo.toISOString().split('T')[0];
      this.f_e_date = currentDate.toISOString().split('T')[0];
    }
    const params = {
      start_date: this.f_s_date,
      end_date: this.f_e_date
    };
    if (this.f_name) params.name = this.f_name;
    if (this.f_env_id) params.env_id = this.f_env_id;
    
    http.get('/api/deploy/iteration/', {params})
      .then(res => this.records = res)
      .finally(() => this.isFetching = false)
  };

  updateDate = (dates) => {
    if (dates && dates.length === 2) {
      this.f_s_date = dates[0].format('YYYY-MM-DD');
      this.f_e_date = dates[1].format('YYYY-MM-DD');
    }
  };

  addRecord = (values) => {
    return http.post('/api/deploy/iteration/', values)
      .then(res => {
        this.records.unshift(res);
        return res;
      })
  };

  updateRecord = (values) => {
    return http.put('/api/deploy/iteration/', values)
      .then(res => {
        for (let item of this.records) {
          if (item.id === res.id) {
            Object.assign(item, res);
            break
          }
        }
        return res;
      })
  };

  deleteRecord = (id) => {
    return http.delete('/api/deploy/iteration/', {params: {id}})
      .then(() => {
        this.records = this.records.filter(x => x.id !== id);
      })
  };

  showDetail = (record) => {
    this.record = record;
    this.detailVisible = true;
    // 加载详情数据
    this.fetchRecordDetail(record.id);
  };

  closeDetail = () => {
    this.record = {};
    this.detailVisible = false;
  };

  // 获取单个迭代的详细信息
  fetchRecordDetail = (id) => {
    return http.get('/api/deploy/iteration/', { params: { id } })
      .then(res => {
        // 更新 record
        if (res && res.length > 0) {
          this.record = res[0];
        }
        // 同时更新 records 列表中的对应项
        const index = this.records.findIndex(x => x.id === id);
        if (index >= 0 && res && res.length > 0) {
          this.records[index] = res[0];
        }
        return res;
      });
  };

  // 发布相关方法
  showPublish = (record) => {
    this.record = record;
    this.publishVisible = true;
    this.fetchPublishStatus(record.id);
  };

  closePublish = () => {
    this.record = {};
    this.publishVisible = false;
    this.publishStatus = [];
    // 关闭时自动刷新迭代列表
    this.fetchRecords();
  };

  fetchPublishStatus = (iterationId) => {
    return http.get('/api/deploy/iteration/publish/', { params: { iteration_id: iterationId } })
      .then(res => {
        this.publishStatus = res;
        return res;
      });
  };

  publishByEnv = (iterationId, envId) => {
    this.isPublishing = true;
    return http.post('/api/deploy/iteration/publish/', {
      iteration_id: iterationId,
      env_id: envId
    })
      .then(res => {
        // 刷新发布状态
        this.fetchPublishStatus(iterationId);
        // 刷新列表
        this.fetchRecords();
        return res;
      })
      .finally(() => {
        this.isPublishing = false;
      });
  };

  // 预传镜像相关方法
  preUploadImage = (iterationId, envId) => {
    return http.post('/api/deploy/iteration/image/', {
      iteration_id: iterationId,
      env_id: envId
    })
      .then(res => {
        // 刷新发布状态
        this.fetchPublishStatus(iterationId);
        return res;
      });
  };

  // 单个镜像重试
  retryImage = (iterationId, detailId) => {
    return http.patch('/api/deploy/iteration/image/', {
      iteration_id: iterationId,
      detail_id: detailId
    })
      .then(res => {
        // 刷新发布状态
        this.fetchPublishStatus(iterationId);
        return res;
      });
  };

  // 重试发布
  retryPublish = (detailId) => {
    return http.patch('/api/deploy/iteration/publish/', {
      detail_id: detailId
    })
      .then(res => {
        // 刷新发布状态
        if (this.record.id) {
          this.fetchPublishStatus(this.record.id);
        }
        // 刷新列表
        this.fetchRecords();
        return res;
      });
  };

  // 更新详情版本
  updateDetailVersion = (detailId, version) => {
    return http.put('/api/deploy/iteration/detail/', {
      detail_id: detailId,
      version: version
    });
  };

  // 移除尚未开始镜像预传或发布的应用
  removeIterationDetail = (detailId) => {
    return http.delete('/api/deploy/iteration/detail/', {
      params: { detail_id: detailId }
    }).then(res => {
      if (this.record.id) {
        this.fetchPublishStatus(this.record.id);
      }
      this.fetchRecords();
      return res;
    });
  };
}
export default new Store()
