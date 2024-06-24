/**
 * Copyright: (c) ccx0lw. https://github.com/ccx0lw/spug
 * Copyright: (c) <fcjava@163.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useState } from 'react';
import { observer, useLocalStore } from 'mobx-react';
import { Modal, Collapse, Steps, Skeleton, Tag } from 'antd';
import { LoadingOutlined } from '@ant-design/icons';
import OutView from './OutView';
import { http, X_TOKEN } from 'libs';
import styles from './index.module.less';
import store from './store';

export default observer(function Console() {
  const outputs = useLocalStore(() => ({}));
  const terms = useLocalStore(() => ({}));
  const [fetching, setFetching] = useState(true);

  useEffect(() => {
    let socket;
    http.get(`/api/docker_image/${store.record.id}/`)
      .then(res => {
        Object.assign(outputs, res.outputs)
        if (res.status === '1') {
          socket = _makeSocket(res.index)
        }
      })
      .finally(() => setFetching(false))
    return () => socket && socket.close()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function _makeSocket(index = 0) {
    const token = store.record.spug_version;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(`${protocol}//${window.location.host}/api/ws/build_image/${token}/?x-token=${X_TOKEN}`);
    socket.onopen = () => socket.send(String(index));
    socket.onmessage = e => {
      if (e.data === 'pong') {
        socket.send(String(index))
      } else {
        index += 1;
        const {key, data, step, status} = JSON.parse(e.data);
        if (!outputs[key]) return
        if (data !== undefined) {
          outputs[key].data += data
          if (terms[key]) terms[key].write(data)
        }
        if (step !== undefined) outputs[key].step = step;
        if (status !== undefined) outputs[key].status = status;
      }
    }
    socket.onerror = () => {
      for (let key of Object.keys(outputs)) {
        outputs[key]['status'] = 'error'
        outputs[key].data = '\u001b[31mWebsocket connection failed!\u001b[0m'
        if (terms[key]) {
          terms[key].reset()
          terms[key].write('\u001b[31mWebsocket connection failed!\u001b[0m')
        }
      }
    }
    return socket
  }

  function StepItem(props) {
    let icon = null;
    if (props.step === props.item.step && props.item.status !== 'error') {
      icon = <LoadingOutlined/>
    }
    return <Steps.Step {...props} icon={icon}/>
  }

  function handleSetTerm(term, key) {
    if (outputs[key] && outputs[key].data) {
      term.write(outputs[key].data)
    }
    terms[key] = term
  }

  let {local, image} = outputs;

  return (
    <div>
      <Modal
        visible={true}
        width="70%"
        footer={null}
        maskClosable={false}
        className={styles.console}
        onCancel={() => store.closeConsole()}
        title={
          <div>
            镜像编译控制台
            {store.record.app_name ? "【"+store.record.app_name+"】" : null}
            {store.record.version ? <Tag color='#f50'>{store.record.version}</Tag> : null}
            {store.record.env_name ? <Tag color="#108ee9">{store.record.env_name}</Tag> : null}
            {store.record.env_prod ? <Tag color="#f50">生产环境</Tag> : null}
          </div>
        }>
          <Skeleton loading={fetching} active>
            {local && (
              <Collapse defaultActiveKey={['0']} className={styles.collapse} style={{marginBottom: 24}}>
                <Collapse.Panel header={(
                  <div className={styles.header}>
                    <b className={styles.title}>{local.title}</b>
                    <Steps size="small" className={styles.step} current={local.step} status={local.status} style={{margin: 0}}>
                      <StepItem title="构建准备" item={local} step={0}/>
                      <StepItem title="检出前任务" item={local} step={1}/>
                      <StepItem title="执行检出" item={local} step={2}/>
                      <StepItem title="检出后任务" item={local} step={3}/>
                      <StepItem title="执行打包" item={local} step={4}/>
                    </Steps>
                  </div>
                )}>
                  <OutView setTerm={term => handleSetTerm(term, 'local')}/>
                </Collapse.Panel>
              </Collapse>
            )}

            {image && (
              <Collapse defaultActiveKey={['0']} className={styles.collapse} style={{marginBottom: 24}}>
                <Collapse.Panel header={(
                  <div className={styles.header}>
                    <b className={styles.title}>{image.title}</b>
                    <Steps size="small" className={styles.step} current={image.step} status={image.status} style={{margin: 0}}>
                      <StepItem title="编译准备" item={image} step={0}/>
                      <StepItem title="数据准备" item={image} step={1}/>
                      <StepItem title="编译镜像" item={image} step={2}/>
                      <StepItem title="清理数据" item={image} step={3}/>
                      <StepItem title="上传镜像" item={image} step={4}/>
                    </Steps>
                  </div>
                )}>
                  <OutView setTerm={term => handleSetTerm(term, 'image')}/>
                </Collapse.Panel>
              </Collapse>
            )}
          </Skeleton>
      </Modal>
    </div>
  )
})
